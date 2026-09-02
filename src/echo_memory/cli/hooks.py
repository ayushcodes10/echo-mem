"""echo-memory install-hooks: register every capture hook in one command.

Until now DEVELOPMENT.md documented four hooks as four JSON blocks to merge by
hand into ~/.claude/settings.json. That is exactly the shape of installation
that half-completes: the hooks are independent, nothing checks that all of them
landed, and a machine missing one looks identical to a machine missing none
until months of memory have quietly not been captured.

The hooks are also not independent in practice. They are one mechanism in four
places - notice a write, sweep for drift, recall on the prompt, gate the stop -
and a set where any single member can be absent is a set that will be.

Written to the user-level settings file, not a project's, because that is what
makes this work in projects that do not exist yet. A hook registered per-project
would have to be remembered for every new repo, which is the failure this whole
change is about.

Existing entries are matched by their marker and replaced, so re-running after
an upgrade repoints the commands at the new paths instead of stacking a second
copy of every hook."""

import json
import os
from pathlib import Path

from echo_memory.cli.install import _atomic_write

SETTINGS = Path.home() / ".claude" / "settings.json"

# Stamped into every entry this writes, so a re-run can tell its own hooks from
# hooks the user or another tool put there and replace only its own.
MARKER = "_echo_memory"

# event, matcher (None = all), script, timeout seconds.
#
# Timeouts differ by what the session is waiting on. SessionStart and
# UserPromptSubmit are latency a human sits through, so they are short and the
# session proceeds without memory if the database is slow. Stop is not in
# anyone's way, and it is the one that has to reach a conclusion.
HOOKS = (
    ("PostToolUse", "Write|Edit", "capture-memory-hook.sh", 10),
    ("SessionStart", None, "session-start-hook.sh", 10),
    ("UserPromptSubmit", None, "user-prompt-hook.sh", 10),
    ("PreCompact", None, "precompact-hook.sh", 10),
    ("Stop", None, "session-stop-hook.sh", 15),
)


def _command(config, scripts_dir: Path, script: str, bin_path: str) -> str:
    """The env is inlined rather than inherited: a hook runs in whatever
    environment the client happens to have, which for a GUI client launched
    from the dock is not the shell where these variables were set."""
    env = {
        "ECHO_MEMORY_USER_ID": config.user_id,
        "ECHO_MEMORY_AGENT_ID": config.agent_id,
        "ECHO_MEMORY_BIN": bin_path,
    }
    url_file = os.environ.get("ECHO_MEMORY_DATABASE_URL_FILE")
    if url_file:
        env["ECHO_MEMORY_DATABASE_URL_FILE"] = url_file
    else:
        env["ECHO_MEMORY_DATABASE_URL"] = config.database_url
    prefix = " ".join(f"{k}={v}" for k, v in env.items())
    return f"{prefix} {scripts_dir / script}"


def plan(config, scripts_dir: Path, bin_path: str) -> list[dict]:
    entries = []
    for event, matcher, script, timeout in HOOKS:
        entry: dict = {
            MARKER: True,
            "hooks": [
                {
                    "type": "command",
                    "command": _command(config, scripts_dir, script, bin_path),
                    "timeout": timeout,
                }
            ],
        }
        if matcher:
            entry["matcher"] = matcher
        entries.append({"event": event, "entry": entry, "script": script})
    return entries


SCRIPT_NAMES = tuple(script for _, _, script, _ in HOOKS)


def is_ours(entry: dict) -> bool:
    """Entries this tool wrote, including ones it wrote before it stamped a
    marker.

    The marker alone is not enough for the machines that matter most: every
    existing install got its hooks by hand-merging the JSON blocks the docs
    used to print, so the entries that most need replacing are exactly the ones
    with no marker. Matching our own script names as well turns the first run
    of this command into an upgrade instead of a silent doubling, where every
    hook would fire twice and every memory file be noticed twice."""
    if entry.get(MARKER):
        return True
    return any(
        command.endswith(name)
        for hook in entry.get("hooks", [])
        for command in [hook.get("command", "")]
        for name in SCRIPT_NAMES
    )


def merge(settings: dict, entries: list[dict]) -> dict:
    """Drop this tool's previous entries, keep everyone else's, add the current
    set. Order within an event does not matter to Claude Code, which runs every
    registered hook for the event."""
    hooks = dict(settings.get("hooks") or {})
    for item in entries:
        existing = [e for e in hooks.get(item["event"], []) if not is_ours(e)]
        hooks[item["event"]] = existing + [item["entry"]]
    return {**settings, "hooks": hooks}


def read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text() or "{}")
    except json.JSONDecodeError as e:
        # Refuse rather than overwrite: this file holds every hook and
        # permission the user has, and rewriting one we could not parse would
        # replace all of it with ours.
        raise ValueError(
            f"{path} is not valid JSON ({e}). Fix it before installing hooks - "
            "overwriting it would drop every other hook and permission it holds."
        ) from e


def apply(config, scripts_dir: Path, bin_path: str, path: Path | None = None) -> dict:
    path = path or SETTINGS
    settings = read_settings(path)
    entries = plan(config, scripts_dir, bin_path)
    merged = merge(settings, entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(merged, indent=2) + "\n")
    return {"path": str(path), "events": [e["event"] for e in entries]}


def render(result: dict, dry_run: bool = False) -> str:
    verb = "Would register" if dry_run else "Registered"
    lines = [f"{verb} {len(result['events'])} hook(s) in {result['path']}:", ""]
    described = {
        "PostToolUse": "queue a memory file the moment it is written",
        "SessionStart": "brief the session, and sweep for files the queue missed",
        "UserPromptSubmit": "retrieve against the prompt before the agent acts",
        "PreCompact": "save what the session learned before context is dropped",
        "Stop": "hold the session open until what it learned is stored",
    }
    lines += [f"  {event:<18} {described.get(event, '')}" for event in result["events"]]
    if not dry_run:
        lines += ["", "Restart any running client for these to take effect."]
    return "\n".join(lines) + "\n"
