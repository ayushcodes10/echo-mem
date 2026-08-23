"""echo-memory: the CLI companion to the MCP server (CEO plan items 3 and
5, "why" and "export"). Reads the same ECHO_MEMORY_* env vars as the
server and resolves scope the same way, never a raw group_id: see the
design doc's Configuration section for why group_id is never typed or
constructed directly."""

import argparse
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from echo_memory.audit.get_audit_log import get_fact_history
from echo_memory.cli.export import export_group
from echo_memory.cli.graph import fetch_graph, render_graph
from echo_memory.cli.graph_html import render_html
from echo_memory.cli.status import fetch_status, render_status
from echo_memory.cli.trial import render_check, render_log, render_recorded, render_start
from echo_memory.cli.why import render_history
from echo_memory.infra.config import ConfigError, load_config
from echo_memory.infra.db import connect
from echo_memory.trial import check, observations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="echo-memory")
    parser.add_argument(
        "--scope", choices=["solo", "shared"], default="solo",
        help="memory scope to operate on (default: solo)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    why_parser = sub.add_parser("why", help="show a fact's audit trail")
    why_parser.add_argument("fact_id", help="fact id, as returned by query_memory")

    export_parser = sub.add_parser("export", help="markdown export of a scope's memory")
    export_parser.add_argument("--out", required=True, type=Path, help="output directory")

    graph_parser = sub.add_parser("graph", help="view a scope's memory graph")
    graph_mode = graph_parser.add_mutually_exclusive_group()
    graph_mode.add_argument(
        "--watch", action="store_true", help="refresh live in the terminal instead of printing once"
    )
    graph_mode.add_argument(
        "--html", type=Path, metavar="PATH",
        help="write a self-contained interactive HTML snapshot to PATH instead of printing to the terminal",
    )
    graph_parser.add_argument(
        "--interval", type=float, default=2.0, help="refresh interval in seconds (with --watch)"
    )

    sub.add_parser("status", help="v1a trial status: which Success Criteria are met so far")

    _add_trial_parser(sub)

    return parser


def _add_trial_parser(sub) -> None:
    """v1a criterion 6 is the only Success Criterion whose bars are human
    judgements (see docs/designs/echo-memory-design.md). These record them, so
    the v1a -> v1b gate is decided from what was actually observed during the
    trial rather than from what anyone remembers of it."""
    trial_parser = sub.add_parser("trial", help="record and review v1a exit-criteria observations")
    trial = trial_parser.add_subparsers(dest="trial_command", required=True)

    start = trial.add_parser("start", help="start the trial clock (the 3-week cap)")
    start.add_argument(
        "--on", type=date.fromisoformat, metavar="YYYY-MM-DD",
        help="start date, if the trial really began before you got round to recording it",
    )
    start.add_argument(
        "--cap-days", type=int, default=observations.DEFAULT_CAP_DAYS,
        help=f"hard cap in days (default: {observations.DEFAULT_CAP_DAYS})",
    )

    save = trial.add_parser(
        "save", help="log a recalled fact that saved re-explaining something"
    )
    save.add_argument("note", help="what it saved re-explaining")
    save.add_argument(
        "--from", dest="written_by", required=True, metavar="TOOL",
        help="the tool that originally recorded the fact (criterion 6 counts an instance "
             "only when this differs from --into)",
    )
    save.add_argument(
        "--into", dest="recalled_by", metavar="TOOL",
        help="the tool that recalled it (default: this CLI's ECHO_MEMORY_AGENT_ID)",
    )

    dup = trial.add_parser("dup", help="confirm two nodes are one entity split in two")
    dup.add_argument("node_a")
    dup.add_argument("node_b")
    dup.add_argument("note", help="why they're the same entity")

    not_dup = trial.add_parser("not-dup", help="dismiss a similar-looking pair as genuinely distinct")
    not_dup.add_argument("node_a")
    not_dup.add_argument("node_b")
    not_dup.add_argument("note", nargs="?", default="reviewed, distinct entities")

    bad_merge = trial.add_parser("bad-merge", help="record an entity resolution that merged two distinct entities")
    bad_merge.add_argument("audit_entry_id", type=int, help="as shown by `echo-memory trial check`")
    bad_merge.add_argument("note", help="which two entities were wrongly merged")

    merge_ok = trial.add_parser("merge-ok", help="confirm an entity resolution was correct")
    merge_ok.add_argument("audit_entry_id", type=int)
    merge_ok.add_argument("note", nargs="?", default="reviewed, correct merge")

    check_parser = trial.add_parser("check", help="criterion 6 status and what's awaiting review")
    check_parser.add_argument(
        "--all", action="store_true", dest="include_exact",
        help="also review exact-name entity resolutions, excluded by default as near-always correct",
    )

    trial.add_parser("log", help="every trial observation recorded so far")


def _run_trial(args, config, conn) -> int:
    group_id = config.group_id(args.scope)

    if args.trial_command == "start":
        started_on = args.on or datetime.now(UTC).date()
        print(render_start(observations.start_trial(conn, started_on, args.cap_days)))
        return 0

    if args.trial_command == "check":
        report = check.build_report(conn, config, include_exact=args.include_exact)
        print(render_check(report), end="")
        return 0

    if args.trial_command == "log":
        group_ids = [config.group_id(scope) for scope in ("solo", "shared")]
        print(render_log(observations.list_observations(conn, group_ids)), end="")
        return 0

    if args.trial_command == "save":
        kind = observations.RECALL_SAVE
        fields = {
            "written_by": args.written_by,
            "recalled_by": args.recalled_by or config.agent_id,
        }
    elif args.trial_command in ("dup", "not-dup"):
        kind = (
            observations.DUPLICATE_NODE
            if args.trial_command == "dup"
            else observations.NOT_DUPLICATE
        )
        fields = {"node_ids": [args.node_a, args.node_b]}
    else:
        kind = (
            observations.BAD_MERGE if args.trial_command == "bad-merge" else observations.MERGE_OK
        )
        fields = {"audit_entry_id": args.audit_entry_id}

    try:
        if "node_ids" in fields:
            fields["node_ids"] = observations.sort_pair(fields["node_ids"])
        observation_id = observations.record(conn, group_id, kind, args.note, **fields)
    except observations.TrialError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except psycopg.errors.UniqueViolation:
        # The unique indexes exist so a second verdict on the same pair or the
        # same resolution can't quietly overwrite the first one.
        print(
            "error: that pair or resolution already has a recorded verdict "
            "(see `echo-memory trial log`)",
            file=sys.stderr,
        )
        return 1
    except psycopg.errors.ForeignKeyViolation:
        print(
            f"error: no audit entry #{args.audit_entry_id} "
            "(ids come from `echo-memory trial check`)",
            file=sys.stderr,
        )
        return 1

    print(render_recorded(kind, observation_id, args.note))
    if kind == observations.RECALL_SAVE and args.written_by == (
        args.recalled_by or config.agent_id
    ):
        print(
            "note: written and recalled by the same tool, so this doesn't count toward "
            "criterion 6's cross-tool bar."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config()
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.command == "status":
        conn = connect(config.database_url)
        print(render_status(fetch_status(conn, config), check.build_report(conn, config)))
        return 0

    if args.command == "trial":
        return _run_trial(args, config, connect(config.database_url))

    group_id = config.group_id(args.scope)

    if args.command == "graph":
        if args.html:
            graph = fetch_graph(connect(config.database_url), group_id)
            args.html.write_text(render_html(args.scope, group_id, graph))
            print(f"Wrote {args.html} ({len(graph['nodes'])} nodes, {len(graph['facts'])} active facts)")
            return 0
        if args.watch:
            try:
                while True:
                    graph = fetch_graph(connect(config.database_url), group_id)
                    os.system("clear")
                    print(render_graph(args.scope, group_id, graph))
                    print(f"(refreshing every {args.interval}s, ctrl-C to stop)")
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                return 0
        graph = fetch_graph(connect(config.database_url), group_id)
        print(render_graph(args.scope, group_id, graph))
        return 0

    conn = connect(config.database_url)

    if args.command == "why":
        result = get_fact_history(conn, group_id, args.fact_id)
        print(render_history(args.fact_id, result["entries"]))
        return 0

    if args.command == "export":
        result = export_group(conn, group_id, args.out)
        print(
            f"Exported {result['n_nodes']} nodes, {result['n_facts']} facts "
            f"to {result['out_dir']}"
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
