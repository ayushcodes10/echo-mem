"""Reads and writes for the v1a trial's recorded judgements (see migration
0002 for why these live outside the audit log).

Nothing here decides anything on its own: a human decides, this records the
decision so `echo-memory status` can report criterion 6 from stored data
instead of from someone's recollection of how the trial went. See
docs/designs/echo-memory-design.md's Success Criteria, criterion 6."""

from datetime import date

from echo_memory.infra.project import UNKNOWN as UNATTRIBUTED
from echo_memory.ingestion.resolution import _node_in_group
from echo_memory.ingestion.write_episode import MAX_STRING_LEN

RECALL_SAVE = "recall_save"
DUPLICATE_NODE = "duplicate_node"
NOT_DUPLICATE = "not_duplicate"
BAD_MERGE = "bad_merge"
MERGE_OK = "merge_ok"

KINDS = (RECALL_SAVE, DUPLICATE_NODE, NOT_DUPLICATE, BAD_MERGE, MERGE_OK)

# Criterion 6's bars, verbatim from the design doc: "at least 3 real instances
# where a recalled fact saved re-explaining something to a different tool; at
# most 1 duplicate node created by entity resolution; zero cases of two
# distinct entities incorrectly merged into one node", over "a trial of real
# cross-tool usage, capped at 3 weeks total".
REQUIRED_SAVES = 3
MAX_DUPLICATES = 1
MAX_BAD_MERGES = 0
DEFAULT_CAP_DAYS = 21


class TrialError(Exception):
    pass


# Recall-save notes reuse write_episode's cap rather than inventing a second
# limit. Until now this writer was CLI-only, where nobody pastes a megabyte;
# an MCP tool hands the column to an agent, and agents paste large things.
MAX_NOTE_LEN = MAX_STRING_LEN


def sort_pair(node_ids: list[str]) -> list[str]:
    """Node pairs are stored sorted so judging (a, b) and later (b, a) collides
    on the unique index instead of recording two contradictory verdicts."""
    if len(node_ids) != 2 or node_ids[0] == node_ids[1]:
        raise TrialError("a duplicate judgement needs exactly two distinct node ids")
    return sorted(node_ids)


def start_trial(
    conn, started_on: date, cap_days: int = DEFAULT_CAP_DAYS, restart_reason: str | None = None
) -> dict:
    """Idempotent unless told otherwise: a second call reports the existing
    start rather than moving it, because a repeated command must never move a
    clock by accident.

    `restart_reason` closes the open run and opens a new one. It is required
    rather than optional for the same purpose a retraction's reason is: the
    record has to show why a measurement stopped counting, or stopping counting
    is indistinguishable from editing the result. The old run keeps its dates
    and its observations keep their timestamps; only the window a tally is
    taken over moves.
    """
    existing = get_trial(conn)
    if existing is not None and not restart_reason:
        return {**existing, "already_started": True}

    previous = None
    if existing is not None:
        conn.execute(
            """UPDATE public.trial_run SET ended_on = %s, ended_reason = %s
                WHERE id = %s""",
            (started_on, restart_reason.strip(), existing["id"]),
        )
        previous = existing

    row = conn.execute(
        "INSERT INTO public.trial_run (started_on, cap_days) VALUES (%s, %s) RETURNING id",
        (started_on, cap_days),
    ).fetchone()
    return {
        "id": row[0], "started_on": started_on, "cap_days": cap_days,
        "already_started": False, "previous": previous,
    }


def get_trial(conn) -> dict | None:
    """The open run. Closed ones are history and are not what a tally is taken
    over."""
    row = conn.execute(
        """SELECT id, started_on, cap_days FROM public.trial_run
            WHERE ended_on IS NULL ORDER BY started_on DESC LIMIT 1"""
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "started_on": row[1], "cap_days": row[2]}


def past_trials(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT started_on, ended_on, cap_days, ended_reason FROM public.trial_run
            WHERE ended_on IS NOT NULL ORDER BY started_on"""
    ).fetchall()
    return [
        {"started_on": r[0], "ended_on": r[1], "cap_days": r[2], "ended_reason": r[3]}
        for r in rows
    ]


def record(
    conn,
    group_id: str,
    kind: str,
    note: str,
    *,
    written_by: str | None = None,
    recalled_by: str | None = None,
    node_ids: list[str] | None = None,
    audit_entry_id: int | None = None,
    delivery: str | None = None,
) -> dict:
    """Record one observation. Returns {"id": int, "created": bool}.

    `created` is False only for a recall save that duplicates one already
    recorded - an agent retrying after a timeout, or logging the same thing
    twice in one turn. Every other kind still raises on conflict, because a
    second verdict on a node pair or a merge review is a real disagreement and
    silently keeping the first one would hide it."""
    if kind not in KINDS:
        raise TrialError(f"unknown observation kind {kind!r}, expected one of {', '.join(KINDS)}")
    note = note.strip()
    if not note:
        raise TrialError("an observation needs a note: the whole value here is being able to read back why")
    if len(note) > MAX_NOTE_LEN:
        raise TrialError(f"note too long: {len(note)} > {MAX_NOTE_LEN} characters")
    if kind == RECALL_SAVE and not (written_by and recalled_by):
        # Without both tools the "to a different tool" clause can't be
        # evaluated, and NULL written_by would also slip past the unique index
        # that stops double-counting (NULLs are distinct). See migration 0005.
        raise TrialError(
            "a recall save needs both written_by and recalled_by: criterion 6 counts an "
            "instance only when a fact written by one tool saved re-explaining to another"
        )

    if node_ids:
        # Both nodes have to be in the scope the verdict is being filed under.
        # A pair judgement is a claim about two entities in one graph, and the
        # scanner that proposes pairs already refuses to cross a group
        # boundary - but nothing checked an id typed by hand, which is how the
        # trial's single recorded duplicate came to be two nodes in DIFFERENT
        # scopes. 'Ayush' in solo and 'Ayush' in shared is correct scoping, not
        # one entity split in two, and it sat in the tallies as the only
        # duplicate this store has ever confirmed.
        #
        # Third instance of the same bug class this week: a caller-supplied
        # node id taken on trust. The first two corrupted the graph; this one
        # corrupted the measurement of the graph.
        outsiders = [n for n in node_ids if not _node_in_group(conn, group_id, n)]
        if outsiders:
            raise TrialError(
                f"node(s) {', '.join(map(str, outsiders))} are not in {group_id}. A pair "
                "judgement is about two entities in one scope; the same name in solo and "
                "shared is correct scoping, not a duplicate."
            )

    if kind == RECALL_SAVE:
        row = conn.execute(
            """INSERT INTO public.trial_observation
                   (kind, group_id, note, written_by, recalled_by, delivery)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (group_id, written_by, note) WHERE kind = 'recall_save'
                   DO NOTHING
               RETURNING id""",
            (kind, group_id, note, written_by, recalled_by, delivery),
        ).fetchone()
        if row is not None:
            return {"id": row[0], "created": True}
        existing = conn.execute(
            """SELECT id FROM public.trial_observation
               WHERE kind = 'recall_save' AND group_id = %s AND written_by = %s AND note = %s""",
            (group_id, written_by, note),
        ).fetchone()
        return {"id": existing[0], "created": False}

    row = conn.execute(
        """INSERT INTO public.trial_observation
               (kind, group_id, note, written_by, recalled_by, node_ids, audit_entry_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (kind, group_id, note, written_by, recalled_by, node_ids, audit_entry_id),
    ).fetchone()
    return {"id": row[0], "created": True}


def list_observations(conn, group_ids: list[str]) -> list[dict]:
    rows = conn.execute(
        """SELECT id, "timestamp", kind, group_id, note, written_by, recalled_by,
                  node_ids, audit_entry_id
           FROM public.trial_observation
           WHERE group_id = ANY(%s)
           ORDER BY "timestamp", id""",
        (group_ids,),
    ).fetchall()
    return [
        {
            "id": r[0], "timestamp": r[1], "kind": r[2], "group_id": r[3], "note": r[4],
            "written_by": r[5], "recalled_by": r[6], "node_ids": r[7], "audit_entry_id": r[8],
        }
        for r in rows
    ]


def counts(conn, group_ids: list[str], since: date | None = None) -> dict:
    """Criterion 6's tallies. Recall saves are split cross-tool vs same-tool:
    only the cross-tool ones count toward the bar (the criterion says "to a
    different tool"), but a same-tool save is still real evidence recall works
    and is worth seeing rather than silently dropping.

    A save whose cited fact has no recorded author does not count either way.
    'unknown' compares unequal to every real agent id, so counting it as
    cross-tool would satisfy `written_by <> recalled_by` for exactly the wrong
    reason - the two sides differ because one is missing, not because two tools
    were involved. Checked here, per save, against the save's own evidence. The
    gate used to check it globally instead, refusing every save in a store that
    held any unattributed fact anywhere; that blocked two saves whose both ends
    name real tools over twenty-seven unrelated facts that cannot be recovered,
    which is a bar nothing could ever clear.

    `since` is the open run's start date. Without it a tally is over everything
    ever recorded, which is not what criterion 6 asks for - it asks for what
    happened "over a trial of real cross-tool usage, capped at 3 weeks". A new
    run that inherited the previous one's bad merges would begin already failed,
    and one that inherited its recall saves would begin already flattered."""
    rows = conn.execute(
        """SELECT kind,
                  count(*) FILTER (
                      WHERE written_by IS NOT NULL AND recalled_by IS NOT NULL
                        AND written_by <> recalled_by
                        AND written_by <> %s AND recalled_by <> %s
                  ) AS cross_tool,
                  count(*) FILTER (
                      WHERE written_by = %s OR recalled_by = %s
                  ) AS unattributed,
                  count(*) AS total
           FROM public.trial_observation
           WHERE group_id = ANY(%s) AND retracted_at IS NULL
             AND (%s::date IS NULL OR "timestamp" >= %s::date)
           GROUP BY kind""",
        (UNATTRIBUTED, UNATTRIBUTED, UNATTRIBUTED, UNATTRIBUTED, group_ids, since, since),
    ).fetchall()
    by_kind = {
        kind: {"cross_tool": cross_tool, "unattributed": unattributed, "total": total}
        for kind, cross_tool, unattributed, total in rows
    }

    (retracted,) = conn.execute(
        """SELECT count(*) FROM public.trial_observation
            WHERE group_id = ANY(%s) AND retracted_at IS NOT NULL
              AND (%s::date IS NULL OR "timestamp" >= %s::date)""",
        (group_ids, since, since),
    ).fetchone()

    (before,) = conn.execute(
        """SELECT count(*) FROM public.trial_observation
            WHERE group_id = ANY(%s) AND retracted_at IS NULL
              AND %s::date IS NOT NULL AND "timestamp" < %s::date""",
        (group_ids, since, since),
    ).fetchone()

    # How many cross-tool saves the read log corroborates. Counted separately
    # from the bar itself: a save with no delivery evidence is not fraudulent,
    # it predates the column that would have recorded it, and conflating the
    # two would retroactively invalidate the record.
    (corroborated,) = conn.execute(
        """SELECT count(*) FROM public.trial_observation
            WHERE group_id = ANY(%s) AND retracted_at IS NULL
              AND kind = %s AND delivery IS NOT NULL
              AND written_by IS DISTINCT FROM recalled_by
              AND written_by <> %s AND recalled_by <> %s
              AND (%s::date IS NULL OR "timestamp" >= %s::date)""",
        (group_ids, RECALL_SAVE, UNATTRIBUTED, UNATTRIBUTED, since, since),
    ).fetchone()

    saves = by_kind.get(RECALL_SAVE, {"cross_tool": 0, "unattributed": 0, "total": 0})
    return {
        "corroborated_saves": corroborated,
        "retracted": retracted,
        "before_this_run": before,
        "cross_tool_saves": saves["cross_tool"],
        "unattributed_saves": saves["unattributed"],
        "same_tool_saves": saves["total"] - saves["cross_tool"] - saves["unattributed"],
        "duplicates": by_kind.get(DUPLICATE_NODE, {}).get("total", 0),
        "bad_merges": by_kind.get(BAD_MERGE, {}).get("total", 0),
        "dismissed_pairs": by_kind.get(NOT_DUPLICATE, {}).get("total", 0),
        "merges_ok": by_kind.get(MERGE_OK, {}).get("total", 0),
    }


def retract(conn, observation_id: int, reason: str) -> dict:
    """Stop an observation counting, without pretending it was never made.

    Deleting the row edits the record of a trial and leaves nobody able to see
    that a mistake happened. Leaving it leaves the exit gate reading a tally
    that is wrong. Retraction is the third option: the row stays, the reason
    stays with it, and the counts skip it.

    The reason is required by a database constraint as well as by this
    function, because a retraction with no reason is a deletion wearing a
    different name.
    """
    reason = (reason or "").strip()
    if not reason:
        raise TrialError(
            "a retraction needs a reason: the point is that the record still "
            "shows what was judged and why it stopped counting"
        )
    if len(reason) > MAX_NOTE_LEN:
        raise TrialError(f"reason too long: {len(reason)} > {MAX_NOTE_LEN} characters")

    row = conn.execute(
        """UPDATE public.trial_observation
              SET retracted_at = now(), retracted_reason = %s
            WHERE id = %s AND retracted_at IS NULL
        RETURNING id, kind::text""",
        (reason, observation_id),
    ).fetchone()
    if row is None:
        existing = conn.execute(
            "SELECT retracted_at FROM public.trial_observation WHERE id = %s",
            (observation_id,),
        ).fetchone()
        if existing is None:
            raise TrialError(f"no observation {observation_id}")
        raise TrialError(f"observation {observation_id} was already retracted")
    return {"id": row[0], "kind": row[1]}
