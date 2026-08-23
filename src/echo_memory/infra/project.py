"""Which project a fact was written from.

Resolved server-side from the process's working directory, never passed in by
the calling agent. Same reasoning as group_id (see the design doc's
Configuration section): a value an agent types is a value an agent types
inconsistently, and "eigen" / "Eigon" / "eigen-backend" across three calls
would make the project dimension worthless for exactly the grouping it exists
to provide.

This works because each session gets its own MCP server process whose cwd is
the project directory - verified against four live processes, three in
work/dugout and one in work/echo-mem. So no per-project registration, env var
or config file is needed for the common case.

ECHO_MEMORY_PROJECT overrides, for callers where cwd means nothing: the direct
Python client embedded in a long-running service (see docs/INTEGRATIONS.md), a
container whose cwd is /app, or a chatbot serving many tenants from one
process."""

import os
import re
import subprocess
from pathlib import Path

UNKNOWN = "unknown"

# Keep it filesystem- and URL-safe, and stable enough to group on: a project
# name ends up in a group-by, a filter chip and a CLI argument.
_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def normalize(name: str) -> str:
    cleaned = _SAFE.sub("-", name.strip()).strip("-.")
    return cleaned[:64] or UNKNOWN


def _git_toplevel(cwd: str) -> str | None:
    """The repo root, so a session started in a subdirectory still reports the
    project rather than the subdirectory it happened to open in."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    top = result.stdout.strip()
    return top or None


def detect_project(cwd: str | None = None, env: dict | None = None) -> str:
    """The repo root's name, else the directory's name, else 'unknown'.

    The git remote is deliberately not consulted: it needs no network here but
    it can disagree with what the operator calls the project (a fork, a rename,
    a monorepo pushed under another org), and the local directory name is what
    they'll type into a filter."""
    env = env if env is not None else os.environ
    override = env.get("ECHO_MEMORY_PROJECT")
    if override:
        return normalize(override)

    try:
        cwd = cwd or os.getcwd()
    except OSError:
        return UNKNOWN

    top = _git_toplevel(cwd)
    name = Path(top or cwd).name
    # Path("/").name is "", and a repo checked out at a filesystem root is not
    # worth guessing about.
    return normalize(name) if name else UNKNOWN


def _walk(base: Path, parts: list[str], budget: list[int]) -> Path | None:
    """Greedy longest-match descent with backtracking.

    Longest-first keeps a hyphenated directory intact when one exists
    (ayush-trade-bot), and backtracking still finds the nested reading when it
    doesn't (yallahaji/Backend). budget bounds the search: the input is an
    untrusted directory name, and a pathological one shouldn't be able to spin
    the filesystem."""
    if not parts:
        return base
    for k in range(len(parts), 0, -1):
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        child = base / "-".join(parts[:k])
        if child.is_dir():
            found = _walk(child, parts[k:], budget)
            if found is not None:
                return found
    return None


def resolve_claude_project_dir(encoded: str) -> Path | None:
    """The real directory behind Claude Code's encoded project-directory name,
    or None if it no longer exists.

    The encoding replaces every path separator with '-', which is ambiguous the
    moment a directory name contains one of its own: .../work/yallahaji-Backend
    and .../work/yallahaji/Backend encode identically. Splitting on dashes
    can't recover either reliably, so resolve against the filesystem instead.
    Parent directories can contain dashes too, so this has to search, not just
    rejoin the tail."""
    parts = [p for p in encoded.lstrip("-").split("-") if p]
    if not parts:
        return None
    return _walk(Path("/"), parts, [4096])


def decode_claude_project_dir(encoded: str) -> str:
    """The project name behind an encoded directory. Falls back to the last
    segment when the directory no longer exists, which is what a deleted
    project leaves behind."""
    resolved = resolve_claude_project_dir(encoded)
    if resolved is not None:
        return normalize(resolved.name)
    parts = [p for p in encoded.lstrip("-").split("-") if p]
    return normalize(parts[-1]) if parts else UNKNOWN
