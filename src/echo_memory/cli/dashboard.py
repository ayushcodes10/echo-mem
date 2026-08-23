"""echo-memory dashboard: one view over every scope and every project.

`graph --html` renders one scope to one file. This renders the whole store:
both scopes, faceted by project, with an inspector that answers the questions
a graph edge should be able to answer about itself.

    what   relation_type, fact, confidence
    when   t_valid, and t_invalid if it has since been superseded
    who    agent_id + session_id (agent_id is why migration 0003 exists: in
           shared scope group_id is user:X:shared, so the writing agent was
           previously unrecoverable)
    where  project
    why    the audit trail - created, superseded from what to what, and the
           entity-resolution rationale behind the nodes it connects

Superseded facts are fetched too, not just active ones. An edge's history is
most of the answer to "why does memory say this now", and dropping the
invalidated versions would leave the inspector able to show only the end
state - the same failure `echo-memory why` exists to fix."""

import json

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.trial import check


def _s(value):
    """agtype scalars arrive quoted; null stays None."""
    if value is None:
        return None
    text = str(value)
    return None if text == "null" else text.strip('"')


def _fetch_nodes(conn, group_id: str) -> list[dict]:
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node {{group_id: $gid}})
            RETURN id(n), n.name, n.type, n.aliases
        $$, %s) AS (id agtype, name agtype, type agtype, aliases agtype)""",
        (json.dumps({"gid": group_id}),),
    ).fetchall()
    out = []
    for node_id, name, type_, aliases in rows:
        parsed = []
        if aliases is not None and str(aliases) != "null":
            try:
                parsed = [a for a in json.loads(str(aliases)) if a]
            except (ValueError, TypeError):
                parsed = []
        out.append(
            {"id": str(node_id), "name": _s(name), "type": _s(type_) or "unknown",
             "aliases": parsed}
        )
    return out


def _fetch_facts(conn, group_id: str) -> list[dict]:
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (a)-[e:FACT {{group_id: $gid}}]->(b)
            RETURN id(e), id(a), a.name, id(b), b.name,
                   e.relation_type, e.fact, e.confidence, e.t_valid, e.t_invalid,
                   e.project, e.agent_id,
                   e.provenance.session_id, e.provenance.source_episode_id
            ORDER BY e.t_valid DESC
        $$, %s) AS (edge_id agtype, source_id agtype, source_name agtype,
                     target_id agtype, target_name agtype, relation_type agtype,
                     fact agtype, confidence agtype, t_valid agtype, t_invalid agtype,
                     project agtype, agent_id agtype, session_id agtype,
                     episode_id agtype)""",
        (json.dumps({"gid": group_id}),),
    ).fetchall()
    facts = []
    for r in rows:
        t_invalid = _s(r[9])
        facts.append(
            {
                "id": str(r[0]),
                "source_id": str(r[1]),
                "source_name": _s(r[2]),
                "target_id": str(r[3]),
                "target_name": _s(r[4]),
                "relation_type": _s(r[5]),
                "fact": _s(r[6]),
                "confidence": _s(r[7]),
                "t_valid": int(_s(r[8])),
                "t_invalid": int(t_invalid) if t_invalid else None,
                "project": _s(r[10]) or "unknown",
                "agent_id": _s(r[11]) or "unknown",
                "session_id": _s(r[12]),
                "episode_id": _s(r[13]),
            }
        )
    return facts


def _fetch_audit(conn, group_id: str) -> tuple[dict, dict]:
    """Audit entries indexed by the edge and by the node they touch, so the
    inspector can show an edge's own history and the resolution rationale for
    the nodes at either end of it."""
    rows = conn.execute(
        """SELECT id, "timestamp", mutation_type, affected_edge_ids::text[],
                  affected_node_id::text, before_fact, after_fact, session_id,
                  summary, resolution_detail
           FROM public.audit_entry WHERE group_id = %s
           ORDER BY "timestamp", id""",
        (group_id,),
    ).fetchall()

    by_edge: dict[str, list] = {}
    by_node: dict[str, list] = {}
    for r in rows:
        entry = {
            "id": r[0],
            "timestamp": r[1].isoformat(),
            "mutation_type": r[2],
            "before_fact": r[5],
            "after_fact": r[6],
            "session_id": r[7],
            "summary": r[8],
            "resolution_detail": r[9],
        }
        for edge_id in r[3] or []:
            by_edge.setdefault(edge_id, []).append(entry)
        if r[4]:
            by_node.setdefault(r[4], []).append(entry)
    return by_edge, by_node


def fetch_dashboard(conn, config, today=None) -> dict:
    scopes = {}
    for scope in ("solo", "shared"):
        group_id = config.group_id(scope)
        by_edge, by_node = _fetch_audit(conn, group_id)
        scopes[scope] = {
            "group_id": group_id,
            "nodes": _fetch_nodes(conn, group_id),
            "facts": _fetch_facts(conn, group_id),
            "audit_by_edge": by_edge,
            "audit_by_node": by_node,
        }

    projects = sorted(
        {f["project"] for s in scopes.values() for f in s["facts"]},
        key=lambda p: (p == "unknown", p),
    )
    agents = sorted({f["agent_id"] for s in scopes.values() for f in s["facts"]})
    return {
        "scopes": scopes,
        "projects": projects,
        "agents": agents,
        "criterion_six": check.build_report(conn, config, today=today),
        "user_id": config.user_id,
    }
