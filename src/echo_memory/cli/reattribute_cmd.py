"""echo-memory reattribute: the command surface for pointing historical facts
at the project they came from. The queries live in reattribute.py."""

from echo_memory.cli.reattribute import reattribute, render_sessions, sessions_by_project


def run(args, config, conn) -> int:
    group_id = config.group_id(args.scope)
    if args.list_sessions or not (args.session and args.project):
        print(render_sessions(args.scope, sessions_by_project(conn, group_id)), end="")
        # Without both --session and --project there is nothing to do, so
        # listing is the helpful response but not a success.
        return 0 if args.list_sessions else 1
    changed = reattribute(conn, group_id, args.session, args.project)
    print(f"Reattributed {changed} fact(s) from session {args.session} to {args.project}.")
    return 0
