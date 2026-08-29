"""echo-memory status: a report against the v1a design doc's Success
Criteria (docs/designs/echo-memory-design.md), computed from real
audit/group_state data rather than a manual query each time someone asks
how the v1a trial is going. Not a CEO-plan scope item.

Criterion 6 (the v1a -> v1b exit criteria) still can't be *checked*
automatically, since each of its bars is a human judgement. It is now
*reported* from stored data, because those judgements have somewhere to live:
`echo-memory trial` records them (see trial/observations.py). What's left
genuinely un-auto-checkable is criterion 3, a real hybrid-retrieval win."""

import json

from echo_memory.cli import adopt
from echo_memory.cli.graph import fetch_graph
from echo_memory.cli.trial import render_criterion_six

GRAPH = "echo_memory"


def writers(conn, group_id: str) -> dict[str, int]:
    """Facts written per agent id.

    The totals above this say nothing about *who* wrote. Once several clients
    are wired, a tool that was registered but has never written is
    indistinguishable from one writing normally - and that is precisely the
    failure this store spent three weeks in: criterion 6 read 0/3 the whole
    time, and nobody could tell whether the recall loop was failing or whether
    only one agent had ever written a fact. It was the latter."""
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->()
            WHERE e.group_id = $gid
            RETURN e.agent_id
        $$, %s) AS (agent_id agtype)""",
        (json.dumps({"gid": group_id}),),
    ).fetchall()
    counts: dict[str, int] = {}
    for (agent_id,) in rows:
        name = str(agent_id).strip('"')
        counts[name] = counts.get(name, 0) + 1
    return counts


def fetch_status(conn, config) -> dict:
    scopes = {}
    for scope in ("solo", "shared"):
        group_id = config.group_id(scope)
        graph = fetch_graph(conn, group_id)

        audit_counts = dict(
            conn.execute(
                """SELECT mutation_type, count(*) FROM public.audit_entry
                   WHERE group_id = %s GROUP BY mutation_type""",
                (group_id,),
            ).fetchall()
        )

        row = conn.execute(
            "SELECT write_episode_count FROM public.group_state WHERE group_id = %s",
            (group_id,),
        ).fetchone()

        scopes[scope] = {
            "group_id": group_id,
            "nodes": len(graph["nodes"]),
            "active_facts": len(graph["facts"]),
            "write_episode_calls": row[0] if row else 0,
            "audit_counts": audit_counts,
            "writers": writers(conn, group_id),
        }
    return scopes


def render_status(scopes: dict, criterion_six: dict) -> str:
    lines = ["Echo Memory - v1a trial status", ""]

    for scope, s in scopes.items():
        lines.append(f"{scope} ({s['group_id']}):")
        lines.append(
            f"  {s['nodes']} nodes, {s['active_facts']} active facts, "
            f"{s['write_episode_calls']} write_episode calls"
        )
        if s["audit_counts"]:
            parts = ", ".join(f"{k}={v}" for k, v in sorted(s["audit_counts"].items()))
            lines.append(f"  audit: {parts}")
        else:
            lines.append("  audit: (none yet)")

        by_agent = dict(s.get("writers") or {})
        # An agent that has written nothing contributes no row to writers(),
        # which counts facts in the graph - so a client wired but silent reads
        # as absent rather than as zero. That is the difference between noticing
        # a mis-wired tool on day 3 and noticing it when the trial expires.
        for client in adopt.adopted_clients():
            by_agent.setdefault(client["agent_id"], 0)
        if by_agent:
            ranked = sorted(by_agent.items(), key=lambda kv: (-kv[1], kv[0]))
            written = ", ".join(f"{agent}={n}" for agent, n in ranked)
            lines.append(f"  written by: {written}")
            silent = [a for a, n in ranked if n == 0]
            if silent:
                lines.append(
                    f"  ! wired but has never written: {', '.join(silent)}"
                )
            if len([a for a, n in ranked if n]) == 1:
                lines.append(
                    f"  ! only {ranked[0][0]} has ever written here, so a cross-tool "
                    "recall save is not yet possible - run `echo-memory install` for a "
                    "second client"
                )
        lines.append("")

    both_have_data = all(s["nodes"] > 0 for s in scopes.values())
    has_entity_resolved = any(
        s["audit_counts"].get("entity_resolved", 0) > 0 for s in scopes.values()
    )
    has_mutation = any(
        s["audit_counts"].get("created", 0) > 0 or s["audit_counts"].get("fact_superseded", 0) > 0
        for s in scopes.values()
    )

    lines.append("v1a Success Criteria (mechanically verifiable ones only):")
    lines.append(f"  [{'x' if both_have_data else ' '}] both solo and shared scopes have real data (criterion 2)")
    lines.append(
        f"  [{'x' if has_entity_resolved else ' '}] at least one entity_resolved audit entry (criteria 1, 4)"
    )
    lines.append(f"  [{'x' if has_mutation else ' '}] at least one fact mutation audit entry (criterion 4)")
    lines.append("")

    lines.append("Criterion 6, the v1a -> v1b exit criteria (recorded via `echo-memory trial`):")
    lines += render_criterion_six(criterion_six)
    lines.append("")
    lines.append(
        "Criterion 3 (a real question where hybrid retrieval beats either signal alone) is "
        "still a human judgement with nowhere to record it. See the design doc's Success "
        "Criteria section for the full text."
    )
    return "\n".join(lines) + "\n"
