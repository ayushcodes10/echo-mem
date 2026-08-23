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
