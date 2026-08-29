"""echo-memory: the CLI companion to the MCP server (CEO plan items 3 and
5, "why" and "export"). Reads the same ECHO_MEMORY_* env vars as the
server and resolves scope the same way, never a raw group_id: see the
design doc's Configuration section for why group_id is never typed or
constructed directly."""

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

from echo_memory.audit.get_audit_log import get_fact_history
from echo_memory.cli import adopt, initdb, reattribute_cmd
from echo_memory.cli import analyse as analyse_cmd
from echo_memory.cli import dashboard as dashboard_cmd
from echo_memory.cli import queue as queue_cmd
from echo_memory.cli import recall as recall_cmd
from echo_memory.cli import session_start as session_start_cmd
from echo_memory.cli import trial as trial_cmd
from echo_memory.cli.benchmark import render as render_benchmark
from echo_memory.cli.benchmark import run as run_benchmark
from echo_memory.cli.dashboard import fetch_dashboard
from echo_memory.cli.dashboard_html import render_dashboard
from echo_memory.cli.export import export_group
from echo_memory.cli.graph import fetch_graph, render_graph
from echo_memory.cli.install import install, render_install
from echo_memory.cli.status import fetch_status, render_status
from echo_memory.cli.why import render_history
from echo_memory.infra.config import ConfigError, load_config
from echo_memory.infra.db import connect
from echo_memory.infra.project import detect_project
from echo_memory.ingestion import bootstrap as bootstrap_mod
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
    _add_project_parsers(sub)

    return parser


def _add_project_parsers(sub) -> None:
    """Project attribution and the automatic-capture queue. See
    infra/project.py for why the project is resolved from cwd rather than
    passed in, and ingestion/capture.py for what the queue is and isn't."""
    dash = sub.add_parser("dashboard", help="one page over every scope and project")
    dash.add_argument(
        "--out", type=Path, metavar="PATH", help="write a self-contained HTML snapshot here"
    )
    dash.add_argument(
        "--serve", action="store_true",
        help="serve it on localhost instead, regenerating on every reload so it stays live",
    )
    dash.add_argument("--port", type=int, default=8787, help="port for --serve (default: 8787)")
    dash.add_argument(
        "--open", action="store_true", dest="open_browser",
        help="open the page in your browser once it is ready",
    )

    reattr = sub.add_parser(
        "reattribute", help="set the project on facts written before projects were recorded"
    )
    reattr.add_argument(
        "--list", action="store_true", dest="list_sessions",
        help="show every session that has written to this scope and its current project",
    )
    reattr.add_argument("--session", metavar="ID", help="session whose facts to reattribute")
    reattr.add_argument("--project", metavar="NAME", help="project to attribute them to")

    notice = sub.add_parser(
        "notice", help="queue a memory file for ingestion (called by the capture hook)"
    )
    notice.add_argument("path", type=Path, help="the memory file that changed")
    notice.add_argument(
        "--project", metavar="NAME",
        help="project it belongs to (default: detected from the file's own path or cwd)",
    )

    pending = sub.add_parser("pending", help="memory files noticed but not yet in the graph")
    pending.add_argument("--project", metavar="NAME", help="only this project")
    pending.add_argument(
        "--done", nargs="+", metavar="PATH", help="mark these paths as ingested"
    )

    rec = sub.add_parser(
        "recall", help="facts matching a prompt, for the UserPromptSubmit hook"
    )
    rec.add_argument("prompt", nargs="?", default="", help="prompt text (default: stdin)")
    rec.add_argument(
        "--hook-json", action="store_true",
        help="emit UserPromptSubmit hook JSON instead of plain text",
    )
    rec.add_argument("--top-k", type=int, default=recall_cmd.DEFAULT_TOP_K)

    ana = sub.add_parser(
        "analyse", help="first-run comprehension pass for an existing project"
    )
    ana.add_argument(
        "--done", action="store_true",
        help="record that the pass has run, so the session briefing stops asking",
    )
    ana.add_argument("--project", metavar="NAME", help="override the detected project")
    ana.add_argument(
        "--root", type=Path, help="project directory to read (default: the current one)"
    )

    brief = sub.add_parser(
        "session-brief",
        help="what memory knows about this project, for the SessionStart hook",
    )
    brief.add_argument(
        "--hook-json", action="store_true",
        help="emit Claude Code's SessionStart hook JSON instead of plain text",
    )
    brief.add_argument(
        "--project", metavar="NAME", help="override the detected project"
    )

    bench = sub.add_parser(
        "benchmark", help="cost and latency baseline for a real ingest + query cycle"
    )
    bench.add_argument(
        "--rounds", type=int, default=5, help="cycles to measure (default: 5)"
    )
    bench.add_argument(
        "--group", metavar="ID", default="benchmark:scratch",
        help="scope to write throwaway probe facts into (default: a dedicated "
             "benchmark group, never your real memory)",
    )

    boot = sub.add_parser(
        "bootstrap", help="import the work that already exists on this machine"
    )
    boot.add_argument(
        "--force", action="store_true", help="sweep again even if discovery has already run"
    )
    boot.add_argument("--dry-run", action="store_true", help="list what would be queued, queue nothing")
    boot.add_argument(
        "--only", action="append", choices=list(bootstrap_mod.SOURCES), metavar="SOURCE",
        help=f"limit to one source; repeatable ({', '.join(bootstrap_mod.SOURCES)})",
    )

    adopt_parser = sub.add_parser(
        "adopt", help="wire every MCP client on this machine to one memory"
    )
    adopt_parser.add_argument(
        "--apply", action="store_true",
        help="actually write the config files (default: show what would change)",
    )
    adopt_parser.add_argument(
        "--force", action="store_true",
        help="repoint a client registered against a different database",
    )

    initdb_parser = sub.add_parser(
        "init-db", help="create or upgrade the schema (works from a pip install)"
    )
    initdb_parser.add_argument(
        "--check", action="store_true",
        help="report the schema version instead of changing anything",
    )

    inst = sub.add_parser(
        "install", help="wire Echo Memory into one project instead of every project"
    )
    inst.add_argument(
        "--no-bootstrap", action="store_true",
        help="skip the first-run sweep for work that already exists on this machine",
    )
    inst.add_argument(
        "root", nargs="?", type=Path, default=Path("."),
        help="project directory (default: the current one)",
    )
    inst.add_argument(
        "--for", dest="targets", choices=["claude", "cursor", "both"], default="claude",
        help="which tool to set up (default: claude)",
    )
    inst.add_argument(
        "--project", metavar="NAME",
        help="project name to attribute facts to (default: the directory's own name)",
    )


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
    check_parser.add_argument(
        "--all-projects", action="store_true", dest="all_projects",
        help="also review node pairs spanning unrelated projects, suppressed by default "
             "because two codebases sharing vocabulary is not a split entity",
    )

    trial.add_parser("log", help="every trial observation recorded so far")


# Each command's logic lives in its own module; main.py wires parsers to them
# and nothing else. Adding a command should not mean editing a shared dispatch
# chain, which is how this file grew to hold twelve of them.
_PROJECT_COMMANDS = {
    "dashboard": dashboard_cmd.run,
    "reattribute": reattribute_cmd.run,
    "notice": queue_cmd.run_notice,
    "pending": queue_cmd.run_pending,
}


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
        return trial_cmd.run(args, config, connect(config.database_url))

    if args.command == "recall":
        prompt = args.prompt or sys.stdin.read()
        conn = connect(config.database_url)
        result = recall_cmd.recall_for_prompt(conn, config, prompt, args.top_k)
        context = recall_cmd.render_context(result)
        if args.hook_json:
            # Nothing relevant: stay silent rather than injecting an empty
            # block into every prompt the user types.
            if context:
                print(recall_cmd.render_hook_output(context))
        else:
            print(context or "(nothing relevant)")
        return 0

    if args.command == "analyse":
        project = args.project or config.project
        root = args.root or Path.cwd()
        conn = connect(config.database_url)
        sources = analyse_cmd.find_sources(root)
        if args.done:
            group_ids = [config.group_id(sc) for sc in ("solo", "shared")]
            n = conn.execute(
                """SELECT count(*) FROM public.audit_entry WHERE group_id = ANY(%s)""",
                (group_ids,),
            ).fetchone()[0]
            analyse_cmd.mark_analysed(conn, project, n, [s["path"] for s in sources])
            print(f"Recorded a comprehension pass for '{project}'.")
            return 0
        if analyse_cmd.has_been_analysed(conn, project):
            print(f"'{project}' has already had a comprehension pass. Re-run anyway:")
        print(analyse_cmd.render_instruction(project, sources))
        return 0

    if args.command == "session-brief":
        project = args.project or config.project
        conn = connect(config.database_url)
        brief = session_start_cmd.build_brief(conn, config, project, Path.cwd())
        context = session_start_cmd.render_brief(brief)
        print(session_start_cmd.render_hook_output(context) if args.hook_json else context)
        return 0

    if args.command == "benchmark":
        from echo_memory.ingestion.embeddings import LocalEmbedder

        conn = connect(config.database_url)
        if args.rounds < 1:
            print("error: --rounds must be at least 1", file=sys.stderr)
            return 1
        print(render_benchmark(run_benchmark(conn, args.group, LocalEmbedder(), args.rounds)),
              end="")
        return 0

    if args.command == "bootstrap":
        conn = connect(config.database_url)
        sources = tuple(args.only) if args.only else bootstrap_mod.SOURCES
        if args.dry_run:
            found = bootstrap_mod.discover(sources=sources)
            print(f"Would queue {len(found)} document(s):")
            for item in found:
                print(f"  [{item['project']}] ({item['source']}) {item['path']}")
            return 0
        result = bootstrap_mod.run(conn, sources=sources, force=args.force)
        print(bootstrap_mod.render(result), end="")
        return 0

    if args.command == "adopt":
        results = (
            adopt.apply(config, force=args.force) if args.apply else adopt.plan(config)
        )
        print(adopt.render(results, applied=args.apply), end="")
        return 0

    if args.command == "init-db":
        try:
            if args.check:
                initdb.current(config.database_url)
            else:
                initdb.upgrade(config.database_url)
                print("Schema is at head. Echo Memory is ready to use.")
        except Exception as e:
            hint = initdb.explain(e)
            if hint is None:
                raise
            print(f"error: {hint}", file=sys.stderr)
            return 1
        return 0

    if args.command == "install":
        targets = ("claude", "cursor") if args.targets == "both" else (args.targets,)
        root = args.root.resolve()
        if not root.is_dir():
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 1
        project = args.project or detect_project(str(root), env={})
        try:
            done = install(root, config, targets, project=project)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(render_install(root, project, targets, done), end="")
        if not args.no_bootstrap:
            conn = connect(config.database_url)
            result = bootstrap_mod.run(conn)
            if not result["skipped"]:
                print()
                print(bootstrap_mod.render(result), end="")
        return 0

    if args.command in _PROJECT_COMMANDS:
        return _PROJECT_COMMANDS[args.command](args, config, connect(config.database_url))

    group_id = config.group_id(args.scope)

    if args.command == "graph":
        if args.html:
            # Renders the dashboard, which supersedes the old single-scope
            # snapshot: every scope, faceted by project, with an inspector that
            # answers what a fact says, who wrote it, when and why. Kept as an
            # alias so a command shipped last week still works.
            conn = connect(config.database_url)
            data = fetch_dashboard(conn, config)
            args.html.write_text(render_dashboard(data))
            n_facts = sum(len(sc["facts"]) for sc in data["scopes"].values())
            print(
                f"Wrote {args.html} ({n_facts} facts across "
                f"{len(data['projects'])} projects)."
            )
            print(
                "Note: --html now renders the full dashboard, so it covers every scope "
                "rather than just --scope, and includes superseded facts as history. "
                "`echo-memory dashboard` is the command for this going forward."
            )
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
