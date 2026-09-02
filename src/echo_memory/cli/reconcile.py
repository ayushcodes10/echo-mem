"""Walk every Claude Code memory file on disk and re-notice what drifted.

The PostToolUse capture hook is the primary path and it works: 24 of 24 memory
files across seven projects were noticed by it. But it can only fire for edits
that happen while it is installed, through a tool call it matches. Three eigen
files were found on 2026-09-02 holding content the queue had never seen - the
hook was not installed when they were first written, or the edit came through a
path it did not match. Nothing detected that, because a queue only knows what it
was told.

So this is the sweep that closes the loop: read what is actually on disk,
compare digests, and reopen anything the graph has not heard. The capture hook
stays the fast path; this is the one that makes a missed hook self-healing
rather than permanent.

Deliberately the same scope as the hook - `*/memory/*.md` minus the index - so
the two cannot disagree about what counts as a memory. If they diverged, the
sweep would either keep reopening files the hook ignores or keep missing files
the hook queues.

Cheap enough to run at session start: sha256 over a few dozen small files. It
does not extract; extraction stays with the agent, because the server never
calls an LLM."""

from pathlib import Path

from echo_memory.infra.project import decode_claude_project_dir
from echo_memory.ingestion import capture

# Where Claude Code keeps per-project memory. One directory per project, its
# name the project path with separators collapsed to dashes.
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# The index file lists the real memories one line each; every one of those
# triggers on its own. Ingesting the index would add a fact per pointer.
INDEX = "MEMORY.md"

SOURCE = "claude-memory"


def memory_files(root: Path | None = None) -> list[tuple[Path, str]]:
    """Every memory file on disk, paired with the project it belongs to."""
    root = root or CLAUDE_PROJECTS
    found: list[tuple[Path, str]] = []
    try:
        project_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return found
    for project_dir in project_dirs:
        memory_dir = project_dir / "memory"
        if not memory_dir.is_dir():
            continue
        project = decode_claude_project_dir(project_dir.name)
        try:
            files = sorted(memory_dir.glob("*.md"))
        except OSError:
            continue
        found += [(f, project) for f in files if f.name != INDEX]
    return found


def reconcile(conn, root: Path | None = None, project: str | None = None) -> dict:
    """Re-notice every memory file whose content the queue has not seen.

    Returns what moved rather than printing, so the session-start hook can stay
    silent when nothing did - which is the common case, and a sweep that
    announces itself every session is noise."""
    known = {
        row[0]: row[1]
        for row in conn.execute("SELECT path, digest FROM public.pending_ingest").fetchall()
    }
    result: dict = {"scanned": 0, "new": [], "changed": [], "unchanged": 0}

    for path, file_project in memory_files(root):
        if project is not None and file_project != project:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            # A file that vanished between listing and reading is not an error
            # worth failing a session start over.
            continue
        result["scanned"] += 1
        digest = capture.digest_of(text)
        previous = known.get(str(path))
        if previous == digest:
            result["unchanged"] += 1
            continue
        capture.notice(conn, str(path), file_project, digest, SOURCE)
        bucket = "new" if previous is None else "changed"
        result[bucket].append({"path": str(path), "project": file_project})
    return result


def render(result: dict) -> str:
    moved = len(result["new"]) + len(result["changed"])
    if not moved:
        return f"Nothing drifted: all {result['scanned']} memory file(s) are in the queue.\n"
    lines = [
        (
            f"Reconciled {result['scanned']} memory file(s): "
            f"{len(result['new'])} never noticed, "
            f"{len(result['changed'])} changed since ingest."
        ),
        "",
    ]
    for label, key in (("never noticed", "new"), ("changed since ingest", "changed")):
        for item in result[key]:
            lines.append(f"  {item['project']}: {Path(item['path']).name}  ({label})")
    lines += ["", "They are queued now. Run `echo-memory pending` to see what to write."]
    return "\n".join(lines) + "\n"
