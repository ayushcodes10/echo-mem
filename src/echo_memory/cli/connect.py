"""echo-memory connect: use the hosted service, with no database of your own.

The self-hosted path needs Docker and a Postgres with Apache AGE. That is the
right default for a tool that promises your memory never leaves your machine,
and it is a lot to ask of somebody deciding whether the idea is any good. This
is the other door: paste a key, and every agent tool on the machine is pointed
at the hosted service.

It writes the same configuration files `install` writes, with one difference
that matters: the hosted server is reached over HTTP with a bearer token rather
than spawned as a local process, so there is no database URL anywhere and
nothing to keep running.

The key is not minted here. Getting one means signing in, which means a
browser, and a CLI that asks for an email and a password would be collecting
credentials it has no business seeing. So this prints where to get one and
takes it as an argument.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ENDPOINT = "https://api.echo-mem.com"

# Keys are minted as em_live_<random>. Checked before anything is written,
# because a config file containing a typo fails at the client with an
# authentication error that says nothing about which of five files is wrong.
KEY_PREFIX = "em_live_"


class ConnectError(Exception):
    pass


def validate(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        raise ConnectError(
            "no key given. Get one at https://api.echo-mem.com - sign in, create a "
            "key for the tool you use, then run: echo-memory connect <key>"
        )
    if not key.startswith(KEY_PREFIX):
        raise ConnectError(
            f"that does not look like an Echo Memory key (they start {KEY_PREFIX!r}). "
            "Copy it from the page that created it; it is shown only once."
        )
    return key


def mcp_entry(api_key: str, endpoint: str = DEFAULT_ENDPOINT) -> dict:
    """The hosted server is HTTP with a bearer token, not a spawned process.

    Nothing here carries a database URL, which is the whole point: a machine
    connected this way has no Postgres, no container and no local state.
    """
    return {
        "type": "http",
        "url": f"{endpoint.rstrip('/')}/mcp",
        "headers": {"Authorization": f"Bearer {api_key}"},
    }


def _merge_json(path: Path, key_path: list[str], entry: dict) -> str:
    """Add our server to a config without disturbing anyone else's.

    These files belong to the user's editor, not to this project. Rewriting one
    wholesale would remove every other MCP server they have registered, which
    is a worse outcome than not being installed.
    """
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as e:
            raise ConnectError(
                f"{path} is not valid JSON, so it was left alone: {e}. "
                "Fix or move it and run this again."
            ) from e

    node = existing
    for part in key_path[:-1]:
        node = node.setdefault(part, {})
    was = key_path[-1] in node
    node[key_path[-1]] = entry

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return "replaced" if was else "added"


def targets(home: Path) -> list[tuple[str, Path, list[str]]]:
    """Where each client keeps its MCP servers.

    Only clients that are actually present. Creating Cursor's config on a
    machine with no Cursor leaves a file nobody asked for, and "installed into
    4 tools" on a machine with one is a lie the next person has to debug.
    """
    found: list[tuple[str, Path, list[str]]] = []
    claude_desktop = home / "Library/Application Support/Claude/claude_desktop_config.json"
    if claude_desktop.parent.is_dir():
        found.append(("Claude Desktop", claude_desktop, ["mcpServers", "echo-memory"]))
    if (home / ".cursor").is_dir():
        found.append(("Cursor", home / ".cursor/mcp.json", ["mcpServers", "echo-memory"]))
    return found


def connect(api_key: str, home: Path, endpoint: str = DEFAULT_ENDPOINT) -> dict:
    key = validate(api_key)
    entry = mcp_entry(key, endpoint)
    written = []
    for name, path, key_path in targets(home):
        action = _merge_json(path, key_path, entry)
        written.append({"client": name, "path": str(path), "action": action})
    return {"endpoint": endpoint, "written": written, "entry": entry}


def render(result: dict) -> str:
    lines = ["Connected to the hosted service.", "", f"  endpoint   {result['endpoint']}/mcp"]
    for w in result["written"]:
        lines.append(f"  {w['action']:<9}  {w['client']} ({w['path']})")
    if not result["written"]:
        lines.append("  no client config files found on this machine")

    # Claude Code is not written to as a file: it owns its own registry and
    # `claude mcp add` is the supported way in. Printing the command is honest
    # about which door each client uses.
    header = result["entry"]["headers"]["Authorization"]
    lines += [
        "",
        "Claude Code keeps its own registry, so add it with:",
        "",
        f"  claude mcp add --transport http --scope user echo-memory {result['endpoint']}/mcp \\",
        f'    --header "{header}"',
        "",
        "Then restart each client. An MCP server holds the code and config it",
        "started with, so a running one will not pick this up.",
        "",
        "Nothing was written for the engine itself: connected this way there is no",
        "local database, and no memory stored on this machine.",
    ]
    return "\n".join(lines) + "\n"


def run(args, _config=None, _conn=None) -> int:
    try:
        result = connect(
            getattr(args, "api_key", "") or "",
            Path.home(),
            getattr(args, "endpoint", None) or DEFAULT_ENDPOINT,
        )
    except ConnectError as e:
        print(f"error: {e}")
        return 1
    print(render(result), end="")
    return 0
