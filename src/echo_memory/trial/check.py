"""The automated half of criterion 6: find the things a human should look at.

Criterion 6's two error bars ("at most 1 duplicate node created by entity
resolution", "zero cases of two distinct entities incorrectly merged into one
node") are both about entity resolution getting it wrong in opposite
directions: splitting one entity across two nodes, or collapsing two into
one. Neither is detectable by the resolver itself, because if it could detect
them it wouldn't have made the mistake. So this doesn't judge; it surfaces
candidates and lets `echo-memory trial dup/not-dup/bad-merge/merge-ok` record
the verdict.

Split candidates come from the resolver's own LOW_THRESHOLD: any two nodes
that ended up separate despite being similar enough that the resolver would
have flagged them as ambiguous had they met in one call. That's exactly the
gap left by the known in-batch limitation documented in ingestion/resolution.py.

Collapse candidates are the `entity_resolved` audit entries: every place a
mention was folded into an existing node. Exact name matches are excluded by
default (they're the common case and nearly always right, and drowning the
review list makes it get skipped); `--all` includes them."""

import json
from datetime import UTC, date, datetime

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.ingestion.resolution import LOW_THRESHOLD
from echo_memory.trial import observations

# Bounded per node rather than a full pairwise scan: this produces a list a
# human reads, and the nearest few neighbours are where a split would hide.
NEIGHBOURS_PER_NODE = 5

EXACT_MATCH_DETAIL = "exact match"


def _unquote(value) -> str:
    return str(value).strip('"')


def _names_for(conn, node_ids: list[str]) -> dict[str, str]:
    if not node_ids:
        return {}
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            UNWIND $ids AS nid
            MATCH (n:Node) WHERE id(n) = nid
            RETURN id(n), n.name, n.type
        $$, %s) AS (node_id agtype, name agtype, type agtype)""",
        (json.dumps({"ids": [int(nid) for nid in node_ids]}),),
    ).fetchall()
    return {
        str(node_id): f"{_unquote(name)} ({_unquote(type_)})" for node_id, name, type_ in rows
    }


def _judged_pairs(conn, group_id: str) -> set[tuple[str, str]]:
    rows = conn.execute(
        """SELECT node_ids FROM public.trial_observation
           WHERE group_id = %s AND node_ids IS NOT NULL""",
        (group_id,),
    ).fetchall()
    return {tuple(node_ids) for (node_ids,) in rows}


def duplicate_candidates(
    conn, group_id: str, threshold: float = LOW_THRESHOLD
) -> list[dict]:
    """Node pairs similar enough to be one entity split in two, minus any pair
    already judged either way. Sorted most-similar first."""
    rows = conn.execute(
        """
        SELECT a.node_id::text, near.node_id::text, near.similarity
        FROM public.node_embedding a
        CROSS JOIN LATERAL (
            SELECT b.node_id, -(b.embedding <#> a.embedding) AS similarity
            FROM public.node_embedding b
            WHERE b.group_id = a.group_id AND b.node_id <> a.node_id
            ORDER BY b.embedding <#> a.embedding
            LIMIT %s
        ) AS near
        WHERE a.group_id = %s AND near.similarity >= %s
        """,
        (NEIGHBOURS_PER_NODE, group_id, threshold),
    ).fetchall()

    # The LATERAL is directional: a's neighbour list and b's both contain the
    # pair. Collapse to one entry per unordered pair, keeping the max score
    # (they're symmetric, so this is really just picking one).
    best: dict[tuple[str, str], float] = {}
    for a_id, b_id, similarity in rows:
        pair = tuple(sorted((a_id, b_id)))
        best[pair] = max(best.get(pair, 0.0), float(similarity))

    judged = _judged_pairs(conn, group_id)
    open_pairs = {pair: score for pair, score in best.items() if pair not in judged}
    if not open_pairs:
        return []

    names = _names_for(conn, sorted({nid for pair in open_pairs for nid in pair}))
    return [
        {
            "node_ids": list(pair),
            "names": [names.get(pair[0], "?"), names.get(pair[1], "?")],
            "similarity": score,
        }
        for pair, score in sorted(open_pairs.items(), key=lambda kv: -kv[1])
    ]


def unreviewed_resolutions(conn, group_id: str, include_exact: bool = False) -> list[dict]:
    """`entity_resolved` audit entries with no recorded verdict yet."""
    sql = """
        SELECT ae.id, ae."timestamp", ae.affected_node_id::text, ae.resolution_detail,
               ae.summary, ae.session_id
        FROM public.audit_entry ae
        LEFT JOIN public.trial_observation obs ON obs.audit_entry_id = ae.id
        WHERE ae.group_id = %s AND ae.mutation_type = 'entity_resolved'
          AND obs.id IS NULL
    """
    params: list = [group_id]
    if not include_exact:
        sql += " AND ae.resolution_detail IS DISTINCT FROM %s"
        params.append(EXACT_MATCH_DETAIL)
    sql += ' ORDER BY ae."timestamp", ae.id'

    rows = conn.execute(sql, tuple(params)).fetchall()
    names = _names_for(conn, [r[2] for r in rows if r[2] is not None])
    return [
        {
            "audit_entry_id": r[0],
            "timestamp": r[1],
            "node_id": r[2],
            "node_name": names.get(r[2], "?"),
            "resolution_detail": r[3],
            "summary": r[4],
            "session_id": r[5],
        }
        for r in rows
    ]


def _elapsed(trial: dict, today: date) -> dict:
    """Day 1 is the start date itself, so a trial started today reads as
    "day 1 of 21" rather than day 0."""
    day = (today - trial["started_on"]).days + 1
    return {
        "started_on": trial["started_on"],
        "cap_days": trial["cap_days"],
        "day": day,
        "days_left": max(trial["cap_days"] - day, 0),
        "expired": day > trial["cap_days"],
    }


def build_report(conn, config, today: date | None = None, include_exact: bool = False) -> dict:
    """Criterion 6 as it stands right now, across both scopes: the trial clock,
    the recorded tallies, and what's still waiting on a human."""
    today = today or datetime.now(UTC).date()
    group_ids = [config.group_id(scope) for scope in ("solo", "shared")]

    trial = observations.get_trial(conn)
    open_items = {
        scope: {
            "duplicate_candidates": duplicate_candidates(conn, config.group_id(scope)),
            "unreviewed_resolutions": unreviewed_resolutions(
                conn, config.group_id(scope), include_exact=include_exact
            ),
        }
        for scope in ("solo", "shared")
    }

    tallies = observations.counts(conn, group_ids)
    return {
        "trial": _elapsed(trial, today) if trial else None,
        "counts": tallies,
        "open": open_items,
        "n_open_pairs": sum(len(s["duplicate_candidates"]) for s in open_items.values()),
        "n_unreviewed": sum(len(s["unreviewed_resolutions"]) for s in open_items.values()),
        "met": {
            "saves": tallies["cross_tool_saves"] >= observations.REQUIRED_SAVES,
            "duplicates": tallies["duplicates"] <= observations.MAX_DUPLICATES,
            "bad_merges": tallies["bad_merges"] <= observations.MAX_BAD_MERGES,
        },
    }
