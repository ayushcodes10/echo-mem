"""echo-memory: the CLI companion to the MCP server (CEO plan items 3 and
5, "why" and "export"). Reads the same ECHO_MEMORY_* env vars as the
server and resolves scope the same way, never a raw group_id: see the
design doc's Configuration section for why group_id is never typed or
constructed directly."""

import argparse
import sys
from pathlib import Path

from echo_memory.audit.get_audit_log import get_fact_history
from echo_memory.cli.export import export_group
from echo_memory.cli.why import render_history
from echo_memory.infra.config import ConfigError, load_config
from echo_memory.infra.db import connect


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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config()
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    conn = connect(config.database_url)
    group_id = config.group_id(args.scope)

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
