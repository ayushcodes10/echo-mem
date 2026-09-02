"""echo-memory adopt: wire every MCP client on this machine to one graph.

`install` is per-project and per-tool. This is the machine-wide equivalent, and
it exists because cross-tool memory is the product's headline claim and had
never once worked end to end - including for its author. Until 2026-08-28
`install` handed every client the same `ECHO_MEMORY_AGENT_ID`, so Claude Code
and Cursor both wrote facts tagged `claude-code` and a cross-tool recall was
undetectable by construction.

Three rules shape everything here, each of them a bug this file exists not to
repeat:

**Never claim a write you cannot verify.** `_merge_json` will happily create a
key in a file no tool reads, and returning "created" would report success for a
client that is not wired. Only clients whose config shape is actually known ship;
the rest are skipped by name. That is why Zed and VS Code are absent: Zed uses
`context_servers` with a nested command object, VS Code uses `servers` with a
`type` field, and both files are JSONC, which `json.loads` rejects. Guessing
their schema is the same mistake as guessing their path.

**Never overwrite what you did not write.** An `echo-memory` entry pointing at a
different database is somebody's deliberate setup. Refuse and name the
difference, rather than silently repointing agents at another graph, where facts
keep being written and simply land somewhere else.

**Default to showing, not doing.** These are machine-global files under no
version control. `--apply` is the flag that writes; without it this prints a
diff. The flag is `--apply` rather than `--dry-run` because a dry run that is on
by default is a thing users misread."""

import json
import os
import shutil
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from echo_memory.cli.install import SERVER_KEY, _merge_json, _server_entry

# Only clients whose config shape is known and testable. Adding one means
# knowing its path, its key path, and that its file is strict JSON.
CLIENTS = {
    "claude-code": {
        "label": "Claude Code",
        "agent_id": "claude-code",
        "path": lambda home: home / ".claude.json",
        "key_path": ("mcpServers", SERVER_KEY),
    },
    "claude-desktop": {
        "label": "Claude Desktop",
        "agent_id": "claude-desktop",
        "path": lambda home: (
            home / "Library" / "Application Support" / "Claude"
            / "claude_desktop_config.json"
        ),
        "key_path": ("mcpServers", SERVER_KEY),
    },
    "cursor": {
        "label": "Cursor",
        "agent_id": "cursor",
        "path": lambda home: home / ".cursor" / "mcp.json",
        "key_path": ("mcpServers", SERVER_KEY),
    },
    "windsurf": {
        "label": "Windsurf",
        "agent_id": "windsurf",
        "path": lambda home: home / ".codeium" / "windsurf" / "mcp_config.json",
        "key_path": ("mcpServers", SERVER_KEY),
    },
}

# Clients whose config this cannot safely rewrite, but whose entry it can
# compose. Codex keeps its MCP servers in ~/.codex/config.toml, which is TOML
# and hand-edited: the stdlib reads it but cannot write it, and the libraries
# that can do not preserve comments or key order. Round-tripping somebody's
# model pins and sandbox settings through a writer that silently reorders them
# is the same violation as overwriting an entry we did not create, so the block
# gets printed and the human pastes it.
MANUAL = {
    "codex": {
        "label": "Codex",
        "agent_id": "codex",
        "path": lambda home: home / ".codex" / "config.toml",
        "why": "config is hand-edited TOML; printing the block instead",
    },
}

# Named so the summary can say why, instead of leaving the user to wonder
# whether their editor was missed or is unsupported.
UNSUPPORTED = {
    "zed": "uses context_servers with a nested command object, and JSONC",
    "vscode": "uses servers with a type field, and JSONC",
}

REGISTRY = Path(".config") / "echo-memory" / "adopted.json"


def _toml_entry(config, agent_id: str, project: str) -> str:
    """The `[mcp_servers.echo-memory]` block, built from the same
    `_server_entry` every other client gets so the two cannot drift."""
    entry = _server_entry(config, project, agent_id)
    env = ", ".join(f'{k} = "{v}"' for k, v in entry["env"].items())
    args = ", ".join(f'"{a}"' for a in entry["args"])
    return (
        f"[mcp_servers.{SERVER_KEY}]\n"
        f'command = "{entry["command"]}"\n'
        f"args = [{args}]\n"
        f"env = {{ {env} }}\n"
    )


def _codex_state(path: Path, want_agent_id: str) -> str:
    """"missing", "wrong-agent-id", or "registered". Read-only: tomllib parses,
    and nothing here writes.

    Checking the agent id and not just the key matters more than it looks. This
    used to return a bool for "is the server present", and on 2026-09-02 it
    reported Codex as already registered while its config carried
    ECHO_MEMORY_AGENT_ID = "claude-code" - written before install.py learned to
    give each client its own id. Every fact Codex wrote would have been filed as
    claude-code, which is precisely the fault that made the v1a cross-tool
    criterion unable to return a signal for the first eight days of the trial.
    A presence check that does not check correctness reports a broken install as
    a healthy one."""
    if not path.exists():
        return "missing"
    try:
        entry = tomllib.loads(path.read_text()).get("mcp_servers", {}).get(SERVER_KEY)
    except (tomllib.TOMLDecodeError, OSError):
        return "missing"
    if entry is None:
        return "missing"
    if (entry.get("env") or {}).get("ECHO_MEMORY_AGENT_ID") != want_agent_id:
        return "wrong-agent-id"
    return "registered"


def manual_steps(config, home: Path | None = None) -> list[dict]:
    """Clients that need a human to paste something, with the thing to paste."""
    home = home or Path.home()
    out = []
    for name, spec in MANUAL.items():
        path = spec["path"](home)
        state = _codex_state(path, spec["agent_id"])
        if not path.exists():
            action, block = "skip", None
        elif state == "registered":
            action, block = "already registered", None
        elif state == "wrong-agent-id":
            # Worth its own action rather than folding into "manual": the entry
            # looks installed, so the operator needs telling that the one field
            # the cross-tool criterion depends on is wrong.
            action, block = "wrong agent id", _toml_entry(
                config, spec["agent_id"], config.project
            )
        else:
            action, block = "manual", _toml_entry(config, spec["agent_id"], config.project)
        out.append({
            "client": name, "label": spec["label"], "path": path,
            "agent_id": spec["agent_id"], "action": action,
            "why": spec["why"], "block": block,
        })
    return out


def registry_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / REGISTRY


def _existing(path: Path, key_path: tuple[str, ...]) -> dict | None:
    """The entry already at key_path, or None. Never raises on a config we
    cannot parse - that is the caller's decision to report, not ours to crash
    on."""
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text())
    except (ValueError, OSError):
        return None
    for key in key_path:
        if not isinstance(doc, dict):
            return None
        doc = doc.get(key)
        if doc is None:
            return None
    return doc if isinstance(doc, dict) else None


def _same_target(existing: dict, proposed: dict) -> bool:
    """Whether two entries point at the same store.

    Not dict equality: `sys.executable` changes when a venv is recreated and the
    credential moves from inline to a file, so exact comparison would turn every
    legitimate re-run into a --force prompt and teach users to type it
    reflexively. What must not change silently is which database and which user.
    """
    a, b = existing.get("env", {}), proposed.get("env", {})

    def url(env: dict) -> str | None:
        """The connection string, resolving a *_FILE reference to its contents.

        Comparing the file path against an inline URL would make every migration
        from inline to indirected look like a repoint to a different database -
        which is exactly what happened the first time this ran against a real
        machine, on the very case the docstring above predicted."""
        path = env.get("ECHO_MEMORY_DATABASE_URL_FILE")
        if path:
            try:
                return Path(path).expanduser().read_text().strip()
            except OSError:
                return None
        return env.get("ECHO_MEMORY_DATABASE_URL")

    return (a.get("ECHO_MEMORY_USER_ID"), url(a)) == (b.get("ECHO_MEMORY_USER_ID"), url(b))


def plan(config, home: Path | None = None) -> list[dict]:
    """What adopt would do, without doing any of it.

    `home` is injectable so tests never touch a real ~/.claude.json, following
    ingestion/bootstrap.py."""
    home = home or Path.home()
    out = []
    for name, spec in CLIENTS.items():
        path = spec["path"](home)
        entry = _server_entry(config, config.project, spec["agent_id"])
        existing = _existing(path, spec["key_path"])
        if not path.exists():
            action, why = "skip", "not installed"
        elif existing is None:
            action, why = "create", "no echo-memory entry yet"
        elif existing == entry:
            action, why = "unchanged", "already correct"
        elif _same_target(existing, entry):
            action, why = "update", "same database, refreshed entry"
        else:
            action, why = "conflict", "registered against a different database or user"
        out.append({
            "client": name, "label": spec["label"], "path": path,
            "agent_id": spec["agent_id"], "entry": entry, "existing": existing,
            "action": action, "why": why, "key_path": spec["key_path"],
        })
    return out


def apply(config, home: Path | None = None, force: bool = False) -> list[dict]:
    """Write the plan. Conflicts are skipped unless force is set.

    A failure on one client never aborts the rest: six targets means six ways to
    fail, and leaving three wired with no record of which is worse than a
    partial success that says so."""
    home = home or Path.home()
    results = []
    for item in plan(config, home):
        if item["action"] in ("skip", "unchanged"):
            results.append(item)
            continue
        if item["action"] == "conflict" and not force:
            results.append(item)
            continue
        try:
            _backup(item["path"])
            state = _merge_json(item["path"], item["key_path"], item["entry"])
            # Read back rather than trusting the write: a running client can
            # flush its own in-memory copy over ours moments later.
            verified = _existing(item["path"], item["key_path"]) == item["entry"]
            results.append({**item, "action": state, "verified": verified})
        except (OSError, ValueError) as e:
            results.append({**item, "action": "failed", "why": str(e)})
    _write_registry(config, results, home)
    return results


def _backup(path: Path) -> None:
    if path.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(path, path.with_name(f"{path.name}.echo-mem-backup-{stamp}"))


def _write_registry(config, results: list[dict], home: Path) -> None:
    """Which clients were wired, so a registered-but-silent one is visible.

    `status.writers()` counts facts in the graph, so an agent that has written
    nothing contributes no row and reads as absent rather than as zero. That is
    the difference between noticing a mis-wired client on day 3 and noticing it
    when the trial expires."""
    path = registry_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    wired = [
        {"client": r["client"], "agent_id": r["agent_id"], "path": str(r["path"])}
        for r in results
        if r["action"] in ("created", "updated", "unchanged")
    ]
    path.write_text(json.dumps({
        "adopted_at": datetime.now(UTC).isoformat(),
        "interpreter": sys.executable,
        "user_id": config.user_id,
        "clients": wired,
    }, indent=2) + "\n")
    os.chmod(path, 0o600)


def adopted_clients(home: Path | None = None) -> list[dict]:
    try:
        return json.loads(registry_path(home).read_text()).get("clients", [])
    except (OSError, ValueError):
        return []


def render(results: list[dict], applied: bool, manual: list[dict] | None = None) -> str:
    verb = "Adopted" if applied else "Would adopt"
    lines = [f"{verb} Echo Memory for the MCP clients on this machine:", ""]
    for r in results:
        mark = {"conflict": "!", "failed": "!", "skip": "-"}.get(r["action"], " ")
        note = f"  ({r['why']})" if r["action"] in ("skip", "conflict", "failed") else ""
        agent = f"  as {r['agent_id']}" if r["action"] not in ("skip", "failed") else ""
        lines.append(f"  {mark} {r['label']:<16} {r['action']:<10}{agent}{note}")
        if r["action"] == "conflict":
            lines.append(f"      {r['path']}")
            lines.append("      pass --force to repoint it")
        if r.get("verified") is False:
            lines.append("      written but not readable back - is the client running?")
    for item in manual or []:
        if item["action"] == "skip":
            lines.append(f"  - {item['label']:<16} skip        (not installed)")
        elif item["action"] == "already registered":
            lines.append(f"    {item['label']:<16} already registered  as {item['agent_id']}")
        elif item["action"] == "wrong agent id":
            lines.append(
                f"  ! {item['label']:<16} registered, but its ECHO_MEMORY_AGENT_ID is not "
                f"'{item['agent_id']}'"
            )
            lines.append(
                f"    Every fact it writes is filed under the wrong tool. Fix {item['path']}:"
            )
            lines.append("")
            lines += [f"      {line}" for line in item["block"].splitlines()]
            lines.append("")
        else:
            lines.append(f"  ~ {item['label']:<16} paste needed  ({item['why']})")
    for name, why in UNSUPPORTED.items():
        lines.append(f"  - {name:<16} unsupported  ({why})")
    lines.append("")

    for item in manual or []:
        if item["action"] != "manual":
            continue
        lines.append(f"Add this to {item['path']}:")
        lines.append("")
        lines += [f"  {ln}" for ln in item["block"].rstrip().split("\n")]
        lines.append("")
    if not applied:
        lines.append("Nothing was written. Re-run with --apply to make these changes.")
    else:
        lines.append("Each client reports its own agent id, so a cross-tool recall is")
        lines.append("now visible. They share one memory: `echo-memory status`.")
    return "\n".join(lines) + "\n"
