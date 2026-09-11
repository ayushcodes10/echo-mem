"""echo-memory reattribute: the command surface for pointing historical facts
at the project they came from, and for recovering the author of facts written
before agent_id was recorded. The queries live in reattribute.py."""

from echo_memory.cli.reattribute import (
    ReattributionError,
    agent_evidence,
    reattribute,
    reattribute_agent,
    render_agent_evidence,
    render_sessions,
    sessions_by_project,
)


def _run_agent(args, group_id, conn) -> int:
    if not args.session:
        print(render_agent_evidence(args.scope, agent_evidence(conn, group_id)), end="")
        # Listing is the helpful response to `--agent` alone, and it is also
        # not a completed instruction. Same convention as the project half.
        return 0 if args.list_sessions else 1
    try:
        changed = reattribute_agent(conn, group_id, args.session)
    except ReattributionError as e:
        print(f"error: {e}")
        return 1
    print(f"Recovered the author of {changed} fact(s) from session {args.session}.")
    return 0


def run(args, config, conn) -> int:
    group_id = config.group_id(args.scope)
    if getattr(args, "agent", False):
        return _run_agent(args, group_id, conn)
    if args.list_sessions or not (args.session and args.project):
        print(render_sessions(args.scope, sessions_by_project(conn, group_id)), end="")
        # Without both --session and --project there is nothing to do, so
        # listing is the helpful response but not a success.
        return 0 if args.list_sessions else 1
    changed = reattribute(conn, group_id, args.session, args.project)
    print(f"Reattributed {changed} fact(s) from session {args.session} to {args.project}.")
    return 0
