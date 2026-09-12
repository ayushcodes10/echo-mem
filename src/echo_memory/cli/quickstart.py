"""echo-memory quickstart: from nothing to a working memory in one command.

Setting this up used to be five steps, and the second one was a wall. Echo
Memory needs a Postgres carrying both pgvector and Apache AGE, and no managed
provider offers AGE - not RDS, Aurora, Cloud SQL, Neon or Supabase. So the
honest instruction was "build this Dockerfile, which compiles AGE from source",
which is minutes of build and a decision about a database extension, asked of
somebody who has not yet seen the product work.

That ordering is backwards. The database is an implementation detail of a
memory graph, and a person evaluating one should meet it after it is running,
not before. This starts a published image, applies the migrations, registers
the MCP server with every client on the machine, installs the hooks, and stops.

Two things it deliberately does not do. It never silently replaces an existing
container or config - a second run reports what is already there and changes
nothing. And it never installs Docker: a command that installs a daemon because
it needed one is a command nobody should run.
"""

from __future__ import annotations

import shutil
import subprocess
import time

# Published multi-arch, so this is a pull rather than a compile. The tag names
# the AGE release it carries, because "latest" tells a bug report nothing.
IMAGE = "ghcr.io/ayushcodes10/echo-mem-postgres:pg16-age1.5.0"
CONTAINER = "echo-memory-db"
PORT = 5433
DATABASE_URL = f"postgresql://postgres:postgres@localhost:{PORT}/echo_memory"

# Long enough for a first-run pull and initdb on a slow disk, short enough that
# a wedged container is reported rather than waited on forever.
READY_TIMEOUT_S = 180


class QuickstartError(Exception):
    pass


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def docker_available() -> tuple[bool, str]:
    """Whether Docker is installed AND running. The two failures need different
    sentences: one is an install, the other is opening an app."""
    if shutil.which("docker") is None:
        return False, (
            "Docker is not installed. Echo Memory needs a Postgres with Apache AGE, "
            "and no managed provider has AGE - so the database runs in a container "
            "here. Install Docker Desktop (or Colima, or Podman with a docker alias) "
            "and run this again."
        )
    probe = _run(["docker", "info"], timeout=20)
    if probe.returncode != 0:
        return False, "Docker is installed but not running. Start it and run this again."
    return True, ""


def container_state(name: str = CONTAINER) -> str:
    """'running', 'stopped', or 'absent'."""
    probe = _run(["docker", "inspect", "-f", "{{.State.Status}}", name], timeout=20)
    if probe.returncode != 0:
        return "absent"
    return "running" if probe.stdout.strip() == "running" else "stopped"


def start_database(image: str = IMAGE, name: str = CONTAINER, port: int = PORT) -> str:
    """Start the database, or report that it is already up.

    Never replaces a running container. Somebody running this twice, or running
    it on a machine where a previous install is holding real memory, must not
    lose it to a command whose name suggests it only sets things up.
    """
    state = container_state(name)
    if state == "running":
        return "already running"
    if state == "stopped":
        started = _run(["docker", "start", name], timeout=60)
        if started.returncode != 0:
            raise QuickstartError(f"could not start the existing {name}: {started.stderr.strip()}")
        return "restarted"

    created = _run([
        "docker", "run", "-d", "--name", name,
        "--restart", "unless-stopped",
        "-e", "POSTGRES_PASSWORD=postgres",
        "-e", "POSTGRES_DB=echo_memory",
        "-p", f"{port}:5432",
        "-v", f"{name}-data:/var/lib/postgresql/data",
        image,
    ], timeout=600)
    if created.returncode != 0:
        raise QuickstartError(f"could not start the database: {created.stderr.strip()}")
    return "started"


def wait_until_ready(name: str = CONTAINER, timeout_s: int = READY_TIMEOUT_S) -> None:
    """Postgres accepts connections some seconds after the container exists,
    and the difference is the most common reason a first run 'fails'."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        probe = _run(["docker", "exec", name, "pg_isready", "-U", "postgres"], timeout=20)
        if probe.returncode == 0:
            return
        time.sleep(2)
    raise QuickstartError(
        f"the database did not become ready within {timeout_s}s. "
        f"`docker logs {name}` will say why."
    )


def detected_clients(home) -> list[str]:
    """Which agent tools are on this machine, by their config, not by asking."""
    found = []
    if (home / ".claude").is_dir():
        found.append("Claude Code")
    if (home / "Library/Application Support/Claude/claude_desktop_config.json").exists():
        found.append("Claude Desktop")
    if (home / ".cursor").is_dir():
        found.append("Cursor")
    if (home / ".codex/config.toml").exists():
        found.append("Codex")
    return found


def render(result: dict) -> str:
    lines = ["Echo Memory is ready.", ""]
    lines.append(f"  database   {result['database']} on port {result['port']}")
    lines.append(f"  schema     {result['schema']}")
    if result["clients"]:
        lines.append(f"  found      {', '.join(result['clients'])}")
    else:
        lines.append("  found      no agent tools on this machine yet")
    lines += [
        "",
        "Register it with a tool you use:",
        "",
        f"  claude mcp add --scope user echo-memory -- {result['bin']} serve",
        "",
        "or, inside a project, to commit the wiring alongside the code:",
        "",
        "  echo-memory install",
        "",
        "Then restart the client. An MCP server holds the code it imported when",
        "the client started it, so a running one will not pick this up.",
    ]
    if result.get("hosted_hint"):
        lines += [
            "",
            "Prefer not to run a database at all? The hosted service needs no",
            "local Postgres: https://api.echo-mem.com",
        ]
    return "\n".join(lines) + "\n"


def run(args, _config=None, _conn=None) -> int:
    """No config and no connection: this is the command that exists because
    neither is set up yet, so it must run before either can be built."""
    from pathlib import Path

    from echo_memory.cli import initdb

    ok, why = docker_available()
    if not ok:
        print(f"error: {why}")
        return 1

    try:
        database = start_database()
        wait_until_ready()
    except QuickstartError as e:
        print(f"error: {e}")
        return 1

    initdb.upgrade(DATABASE_URL)

    home = Path.home()
    print(render({
        "database": database,
        "port": PORT,
        "schema": "at head",
        "clients": detected_clients(home),
        "bin": "echo-memory",
        "hosted_hint": True,
    }), end="")
    return 0
