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
from echo_memory.infra.project import UNKNOWN as UNATTRIBUTED
from echo_memory.infra.project import normalize


class ReattributionError(Exception):
    pass


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


# --- agent attribution, recovered rather than asserted -------------------------
#
# Project attribution above is operator knowledge: only a human knows which
# project a session belonged to, so a human says so. Agent attribution is not
# like that. Guessing it is precisely what migration 0011 refused to do when it
# backfilled absent agent_ids to 'unknown' instead of to 'claude-code', and that
# refusal was right: a fact claiming an author it cannot support is worse than
# one admitting it has none.
#
# There is one case where it does not have to be a guess. A session is one
# tool's conversation, so if some facts from a session carry a real agent_id and
# others carry none, the others were written by that same tool - evidence from
# inside the store, not recollection from outside it. Where a session offers no
# such evidence, or offers two different agents, this refuses rather than
# picking one.


def agent_evidence(conn, group_id: str) -> list[dict]:
    """Per session: how many facts lack an author, and what the rest of that
    session says about who wrote them."""
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT {{group_id: $gid}}]->()
            RETURN e.provenance.session_id, e.agent_id, count(e)
        $$, %s) AS (session_id agtype, agent_id agtype, n agtype)""",
        (json.dumps({"gid": group_id}),),
    ).fetchall()

    by_session: dict[str, dict[str, int]] = {}
    for session, agent, n in rows:
        # An absent agent_id and the literal 'unknown' are the same condition
        # wearing two hats: AGE drops a property whose value is null at CREATE,
        # so a writer that passed None left no key, and migration 0011 turned
        # what it could find into 'unknown'.
        key = str(agent).strip('"') if agent is not None else UNATTRIBUTED
        by_session.setdefault(str(session).strip('"'), {})[key] = int(str(n))

    evidence = []
    for session, tally in by_session.items():
        missing = tally.get(UNATTRIBUTED, 0)
        if not missing:
            continue
        attributed = {a: n for a, n in tally.items() if a != UNATTRIBUTED}
        evidence.append({
            "session_id": session,
            "missing": missing,
            "attributed": attributed,
            # One agent and only one. Two would mean the session id is shared
            # by two tools, and then nothing here can say which wrote what.
            "recoverable_as": next(iter(attributed)) if len(attributed) == 1 else None,
        })
    return sorted(evidence, key=lambda e: (e["recoverable_as"] is None, e["session_id"]))


def reattribute_agent(conn, group_id: str, session_id: str) -> int:
    """Give one session's unattributed facts the author the rest of that
    session already evidences. Refuses when the session does not evidence one,
    because the alternative is inventing provenance."""
    match = next(
        (e for e in agent_evidence(conn, group_id) if e["session_id"] == session_id), None
    )
    if match is None:
        raise ReattributionError(f"session {session_id} has no unattributed facts")
    if match["recoverable_as"] is None:
        found = ", ".join(sorted(match["attributed"])) or "nothing"
        raise ReattributionError(
            f"session {session_id} does not evidence one author ({found}), so its "
            f"{match['missing']} unattributed fact(s) stay unattributed. They predate "
            "attribution and there is nothing in the store that can recover them."
        )

    agent = match["recoverable_as"]
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT {{group_id: $gid}}]->()
            WHERE e.provenance.session_id = $sid
              AND (e.agent_id = $unknown OR e.agent_id IS NULL)
            SET e.agent_id = $agent
            RETURN id(e)
        $$, %s) AS (edge_id agtype)""",
        (json.dumps(
            {"gid": group_id, "sid": session_id, "agent": agent, "unknown": UNATTRIBUTED}
        ),),
    ).fetchall()
    return len(rows)


def render_agent_evidence(scope: str, evidence: list[dict]) -> str:
    if not evidence:
        return f"Every fact in {scope} records who wrote it.\n"

    lines = [f"Facts in {scope} with no recorded author:", ""]
    for e in evidence:
        if e["recoverable_as"]:
            lines.append(
                f"  {e['missing']:>3} fact(s)  session {e['session_id']}  "
                f"-> {e['recoverable_as']} (the rest of the session says so)"
            )
        else:
            found = ", ".join(f"{a} x{n}" for a, n in sorted(e["attributed"].items()))
            lines.append(
                f"! {e['missing']:>3} fact(s)  session {e['session_id']}  "
                f"-> unrecoverable ({found or 'no attributed fact in this session'})"
            )

    if any(e["recoverable_as"] for e in evidence):
        lines += [
            "",
            "Recover the evidenced ones with:",
            f"  echo-memory --scope {scope} reattribute --agent --session <id>",
        ]
    if any(not e["recoverable_as"] for e in evidence):
        lines += [
            "",
            "The rest stay unattributed. Nothing in the store says who wrote them, and",
            "a fact claiming an author it cannot support is worse than one admitting",
            "it has none.",
        ]
    return "\n".join(lines) + "\n"
