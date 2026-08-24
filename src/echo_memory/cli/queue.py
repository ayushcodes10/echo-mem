"""echo-memory notice / pending: the capture queue's command surface.

`notice` is what the PostToolUse hook calls when a memory file is written;
`pending` is how a human or an agent sees what the graph has not heard about
yet. The queue itself lives in ingestion/capture.py - this module is only the
CLI half."""

import sys
from pathlib import Path

from echo_memory.infra.project import decode_claude_project_dir
from echo_memory.ingestion import capture


def project_for_memory_file(path: Path, fallback: str) -> str:
    """A Claude Code memory file lives at
    ~/.claude/projects/<encoded-project-path>/memory/<name>.md, and the
    encoded segment is the project's absolute path with separators replaced by
    dashes. Decoding it gives what detect_project() would have returned had the
    write happened there. Falling back to the hook's own cwd would attribute
    every project's memories to whichever repo the agent happened to be
    sitting in."""
    parts = path.resolve().parts
    if "projects" in parts:
        encoded = parts[parts.index("projects") + 1 :]
        if encoded:
            return decode_claude_project_dir(encoded[0])
    return fallback


def run_notice(args, config, conn) -> int:
    if not args.path.exists():
        print(f"error: no such file: {args.path}", file=sys.stderr)
        return 1
    project = args.project or project_for_memory_file(args.path, config.project)
    result = capture.notice_file(conn, args.path, project)
    if result["changed"]:
        print(f"Queued {args.path} for ingestion ({project}).")
    else:
        print(f"Already queued and unchanged: {args.path}")
    return 0


def run_pending(args, _config, conn) -> int:
    if args.done:
        print(f"Marked {capture.mark_ingested(conn, args.done)} file(s) as ingested.")
        return 0
    queued = capture.pending(conn, args.project)
    if not queued:
        print("Nothing pending: every noticed memory file is in the graph.")
        return 0
    print(f"{len(queued)} document(s) noticed but not yet in the graph:")
    current_project = None
    for item in queued:
        if item["project"] != current_project:
            current_project = item["project"]
            print(f"\n  {current_project}")
        print(f"    ({item['source']}) {item['path']}")
    print(
        "\nRead each one and call write_episode with the entities and facts it states, "
        "then: echo-memory pending --done <path>..."
    )
    return 0
