"""echo-memory reattribute: set the project on facts written before the
project dimension existed.

Migration 0003 backfills every pre-existing fact to 'unknown' rather than
guessing, because session ids are per-install and a migration in an
open-source repo has no business hardcoding one person's history. This is the
operator-side other half: they know which session was which project, so they
say so once and the graph stops saying 'unknown'.

Deliberately keyed on session_id rather than a date range or a node name: a
session is the one thing that was unambiguously inside a single project, and
it's what provenance already records."""

import json

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.project import normalize


def sessions_by_project(conn, group_id: str) -> list[dict]:
    """Every session that has written to this scope, with its current project
    attribution and fact count, so the operator can see what needs saying."""
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT {{group_id: $gid}}]->()
            RETURN e.provenance.session_id, e.project, count(e)
        $$, %s) AS (session_id agtype, project agtype, n agtype)""",
        (json.dumps({"gid": group_id}),),
    ).fetchall()
    return sorted(
        (
            {
                "session_id": str(s).strip('"'),
                "project": str(p).strip('"') if p is not None else None,
                "facts": int(str(n)),
            }
            for s, p, n in rows
        ),
        key=lambda r: (r["project"] or "", r["session_id"]),
    )


def reattribute(conn, group_id: str, session_id: str, project: str) -> int:
    """Point every fact from one session at a project. Returns the number of
    facts changed."""
    project = normalize(project)
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT {{group_id: $gid}}]->()
            WHERE e.provenance.session_id = $sid
            SET e.project = $project
            RETURN id(e)
        $$, %s) AS (edge_id agtype)""",
        (json.dumps({"gid": group_id, "sid": session_id, "project": project}),),
    ).fetchall()
    return len(rows)


def render_sessions(scope: str, sessions: list[dict]) -> str:
    if not sessions:
        return f"No facts recorded in {scope} yet.\n"

    lines = [f"Sessions that have written to {scope}:", ""]
    for s in sessions:
        project = s["project"] or "unknown"
        marker = "  " if project != "unknown" else "! "
        lines.append(f"{marker}{project:<20} {s['facts']:>4} facts   session {s['session_id']}")
    if any((s["project"] or "unknown") == "unknown" for s in sessions):
        lines += [
            "",
            "Facts marked unknown predate the project dimension. Attribute them with:",
            f"  echo-memory --scope {scope} reattribute --session <id> --project <name>",
        ]
    return "\n".join(lines) + "\n"
