"""First-run discovery: find the work that already exists.

A fresh Echo Memory store is empty, but the machine it runs on usually isn't.
By the time anyone installs this there are already months of recorded
decisions sitting in per-project memory files, gstack learnings and CLAUDE.md
files. Starting from zero and waiting for new sessions to slowly refill the
graph wastes all of it, and means the user re-explains things they already
wrote down once.

So on first initialisation, sweep every reference store on the machine and
queue what's there. Each adapter below reads one kind of reference and yields
the documents it points at, along with the project each belongs to.

This queues; it does not extract - the same boundary as the capture hook.
Turning a document into entities and facts needs a model, and the server never
calls one (design doc, MCP tool contract, architecture pivot). Discovery is
therefore complete and automatic; ingestion is agent-driven, and a machine with
sixty documents on it will take more than one turn to work through.

Deliberately NOT swept: raw session transcripts (~/.claude/projects/*.jsonl).
They're enormous, mostly tool output, and the signal in them has already been
distilled into the memory files that ARE swept. Queuing thousands of
transcripts would bury the documents actually worth reading.

An adapter for Claude Code's company-memory digests was removed once that tool
was uninstalled. Its content was derivative by construction - every entry cited
the memory file it came from - so the sweep loses nothing the per-project
memories don't already carry."""

import json
from pathlib import Path

from echo_memory.infra.project import (
    UNKNOWN,
    decode_claude_project_dir,
    normalize,
    resolve_claude_project_dir,
)
from echo_memory.ingestion import capture

CLAUDE_MEMORY = "claude-memory"
GSTACK_LEARNINGS = "gstack-learnings"
PROJECT_INSTRUCTIONS = "project-instructions"

SOURCES = (CLAUDE_MEMORY, GSTACK_LEARNINGS, PROJECT_INSTRUCTIONS)

# MEMORY.md is an index whose every line points at a real memory file that is
# itself discovered; queuing it would ask the agent to re-read the same facts
# as a table of contents.
_SKIP_NAMES = {"MEMORY.md"}


def _claude_memories(home: Path) -> list[dict]:
    found = []
    for memory_dir in sorted(home.glob(".claude/projects/*/memory")):
        project = decode_claude_project_dir(memory_dir.parent.name)
        for path in sorted(memory_dir.glob("*.md")):
            if path.name in _SKIP_NAMES:
                continue
            found.append({"path": path, "project": project, "source": CLAUDE_MEMORY})
    return found


def _gstack_learnings(home: Path, known: set[str]) -> list[dict]:
    """gstack names its directories <owner>-<repo> sometimes and <repo> other
    times, and neither is recoverable by splitting on dashes when the repo name
    contains one. Match against projects the authoritative sources already
    named, and only fall back to the raw directory name."""
    found = []
    for path in sorted(home.glob(".gstack/projects/*/learnings.jsonl")):
        raw = path.parent.name
        project = normalize(raw)
        if raw not in known:
            suffixes = [k for k in known if raw.endswith(f"-{k}")]
            if suffixes:
                project = max(suffixes, key=len)
        found.append({"path": path, "project": project, "source": GSTACK_LEARNINGS})
    return found


def _project_instructions(project_dirs: dict[str, Path]) -> list[dict]:
    found = []
    for project, directory in sorted(project_dirs.items()):
        path = directory / "CLAUDE.md"
        if path.is_file():
            found.append({"path": path, "project": project, "source": PROJECT_INSTRUCTIONS})
    return found


def _project_dirs(home: Path) -> dict[str, Path]:
    """Every project directory the reference stores point at. This is what
    "from what all reference it has" resolves to: the stores name the paths,
    so discovery never has to guess where a user keeps their work.

    Only Claude Code's encoded project directories name paths now, so a
    project is discoverable here exactly when it has a directory under
    ~/.claude/projects that still resolves on disk."""
    dirs: dict[str, Path] = {}
    for encoded in sorted(home.glob(".claude/projects/*")):
        if not encoded.is_dir():
            continue
        candidate = resolve_claude_project_dir(encoded.name)
        if candidate is not None:
            dirs[normalize(candidate.name)] = candidate
    return dirs


def discover(home: Path | None = None, sources: tuple[str, ...] = SOURCES) -> list[dict]:
    """Everything worth queuing, deduplicated by path. Ordered most-specific
    first: a hand-written memory note says more per line than a generated
    digest, so it should be the thing an agent reads first if it only gets
    through part of the queue."""
    home = home or Path.home()
    project_dirs = _project_dirs(home)
    known = set(project_dirs)

    found: list[dict] = []
    if CLAUDE_MEMORY in sources:
        found += _claude_memories(home)
    if GSTACK_LEARNINGS in sources:
        found += _gstack_learnings(home, known)
    if PROJECT_INSTRUCTIONS in sources:
        found += _project_instructions(project_dirs)

    seen, unique = set(), []
    for item in found:
        resolved = str(item["path"].resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append({**item, "path": item["path"], "project": item["project"] or UNKNOWN})
    return unique


def has_run(conn) -> bool:
    return conn.execute("SELECT 1 FROM public.bootstrap_state LIMIT 1").fetchone() is not None


def _mark_run(conn, n_found: int) -> None:
    conn.execute(
        """INSERT INTO public.bootstrap_state (discovered_at, n_found)
           VALUES (now(), %s)
           ON CONFLICT (id) DO UPDATE SET discovered_at = now(), n_found = EXCLUDED.n_found""",
        (n_found,),
    )


def run(conn, home: Path | None = None, sources: tuple[str, ...] = SOURCES, force: bool = False):
    """Queue everything discovered. Idempotent: capture.notice skips documents
    already queued and unchanged, so re-running after new work lands picks up
    only what actually moved."""
    if has_run(conn) and not force:
        return {"skipped": True, "queued": 0, "found": 0, "by_source": {}, "by_project": {}}

    found = discover(home, sources)
    queued = 0
    by_source: dict[str, int] = {}
    by_project: dict[str, int] = {}
    for item in found:
        try:
            result = capture.notice(
                conn, str(item["path"]), item["project"],
                capture.digest_of(item["path"].read_text(errors="replace")),
                source=item["source"],
            )
        except OSError:
            continue
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1
        by_project[item["project"]] = by_project.get(item["project"], 0) + 1
        if result["changed"]:
            queued += 1

    _mark_run(conn, len(found))
    return {
        "skipped": False,
        "queued": queued,
        "found": len(found),
        "by_source": by_source,
        "by_project": by_project,
    }


def render(result: dict) -> str:
    if result["skipped"]:
        return (
            "Discovery has already run; nothing rescanned. Use --force to sweep again "
            "after new reference material lands.\n"
        )
    if not result["found"]:
        lines = [
            "Found no existing work to import.",
            "",
            (
                "Looked for per-project memory files, gstack learnings and CLAUDE.md "
                "files under your home directory."
            ),
        ]
        return "\n".join(lines) + "\n"

    lines = [
        f"Found {result['found']} existing document(s); {result['queued']} newly queued.",
        "",
        "By source:",
    ]
    lines += [f"  {source:<22} {n}" for source, n in sorted(result["by_source"].items())]
    lines += ["", "By project:"]
    lines += [
        f"  {project:<22} {n}"
        for project, n in sorted(result["by_project"].items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    lines += [
        "",
        (
            "These are queued, not yet in the graph: turning a document into entities and "
            "facts needs a model, and this server never calls one. Run `echo-memory pending` "
            "to see the queue, read each document, call write_episode with what it states, "
            "then `echo-memory pending --done <path>`."
        ),
    ]
    return "\n".join(lines) + "\n"


def parse_learnings(path: Path) -> list[dict]:
    """gstack learnings are JSONL, one insight per line. Exposed so an agent
    working the queue can read them structurally instead of guessing at the
    format."""
    out = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
