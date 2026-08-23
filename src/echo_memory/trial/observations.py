"""Reads and writes for the v1a trial's recorded judgements (see migration
0002 for why these live outside the audit log).

Nothing here decides anything on its own: a human decides, this records the
decision so `echo-memory status` can report criterion 6 from stored data
instead of from someone's recollection of how the trial went. See
docs/designs/echo-memory-design.md's Success Criteria, criterion 6."""

from datetime import date

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


def start_trial(conn, started_on: date, cap_days: int = DEFAULT_CAP_DAYS) -> dict:
    """Idempotent: a second call reports the existing start rather than moving
    it. Restarting the clock is a decision worth making explicitly (drop the
    row), not something a repeated command should do by accident."""
    existing = get_trial(conn)
    if existing is not None:
        return {**existing, "already_started": True}
    conn.execute(
        "INSERT INTO public.trial_run (started_on, cap_days) VALUES (%s, %s)",
        (started_on, cap_days),
    )
    return {"started_on": started_on, "cap_days": cap_days, "already_started": False}


def get_trial(conn) -> dict | None:
    row = conn.execute("SELECT started_on, cap_days FROM public.trial_run LIMIT 1").fetchone()
    if row is None:
        return None
    return {"started_on": row[0], "cap_days": row[1]}


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

    if kind == RECALL_SAVE:
        row = conn.execute(
            """INSERT INTO public.trial_observation
                   (kind, group_id, note, written_by, recalled_by)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (group_id, written_by, note) WHERE kind = 'recall_save'
                   DO NOTHING
               RETURNING id""",
            (kind, group_id, note, written_by, recalled_by),
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


def counts(conn, group_ids: list[str]) -> dict:
    """Criterion 6's tallies. Recall saves are split cross-tool vs same-tool:
    only the cross-tool ones count toward the bar (the criterion says "to a
    different tool"), but a same-tool save is still real evidence recall works
    and is worth seeing rather than silently dropping."""
    rows = conn.execute(
        """SELECT kind,
                  count(*) FILTER (
                      WHERE written_by IS NOT NULL AND recalled_by IS NOT NULL
                        AND written_by <> recalled_by
                  ) AS cross_tool,
                  count(*) AS total
           FROM public.trial_observation
           WHERE group_id = ANY(%s)
           GROUP BY kind""",
        (group_ids,),
    ).fetchall()
    by_kind = {kind: {"cross_tool": cross_tool, "total": total} for kind, cross_tool, total in rows}

    saves = by_kind.get(RECALL_SAVE, {"cross_tool": 0, "total": 0})
    return {
        "cross_tool_saves": saves["cross_tool"],
        "same_tool_saves": saves["total"] - saves["cross_tool"],
        "duplicates": by_kind.get(DUPLICATE_NODE, {}).get("total", 0),
        "bad_merges": by_kind.get(BAD_MERGE, {}).get("total", 0),
        "dismissed_pairs": by_kind.get(NOT_DUPLICATE, {}).get("total", 0),
        "merges_ok": by_kind.get(MERGE_OK, {}).get("total", 0),
    }
