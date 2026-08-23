"""Reads and writes for the v1a trial's recorded judgements (see migration
0002 for why these live outside the audit log).

Nothing here decides anything on its own: a human decides, this records the
decision so `echo-memory status` can report criterion 6 from stored data
instead of from someone's recollection of how the trial went. See
docs/designs/echo-memory-design.md's Success Criteria, criterion 6."""

from datetime import date

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
) -> int:
    if kind not in KINDS:
        raise TrialError(f"unknown observation kind {kind!r}, expected one of {', '.join(KINDS)}")
    if not note.strip():
        raise TrialError("an observation needs a note: the whole value here is being able to read back why")

    row = conn.execute(
        """INSERT INTO public.trial_observation
               (kind, group_id, note, written_by, recalled_by, node_ids, audit_entry_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (kind, group_id, note.strip(), written_by, recalled_by, node_ids, audit_entry_id),
    ).fetchone()
    return row[0]


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
