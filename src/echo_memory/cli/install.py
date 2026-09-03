"""echo-memory install: wire Echo Memory into one project instead of every
project.

The user-scoped MCP registration in the README is the right default for a
personal machine: register once, every session in every repo can write. But
that's not always what's wanted. A single Claude project, a repo whose memory
shouldn't mingle with the rest, a Cursor workspace, a machine shared with
someone else - all of those want Echo Memory scoped to one directory, and
committed alongside the code rather than living in a global config the rest of
the team can't see.

This writes the per-project equivalents:

  <project>/.claude/skills/echo-memory/SKILL.md   how an agent should use it
  <project>/.mcp.json                             Claude Code, project scope
  <project>/.cursor/mcp.json                      Cursor
  <project>/.cursor/rules/echo-memory.mdc         Cursor's equivalent of a skill

The skill is the half that matters even where MCP is already registered: the
tools being available is not the same as an agent knowing to call them at the
right moments, which is most of what SKILL.md is for.

Every file is merged, never overwritten wholesale: .mcp.json commonly already
holds other servers, and clobbering a project's MCP config to add one entry
would be a rude way to install anything."""

import json
import os
import sys
from importlib import resources
from pathlib import Path

from echo_memory.infra.project import detect_project

SKILL_DIR = Path(".claude") / "skills" / "echo-memory"
SERVER_KEY = "echo-memory"


def skill_text() -> str:
    return resources.files("echo_memory.skill").joinpath("SKILL.md").read_text()


# The agent id each client announces itself as. Until 2026-08-28 every client
# was handed `config.agent_id`, so Claude Code and Cursor both wrote facts
# tagged `claude-code` - which made the v1a cross-tool criterion
# (`written_by != recalled_by`) impossible to satisfy no matter how well recall
# worked, because there was only ever one writer in the data. The command that
# exists to enable cross-tool memory was the thing preventing it from being
# observed.
CLIENT_AGENT_IDS = {
    "claude": "claude-code",
    "claude-desktop": "claude-desktop",
    "cursor": "cursor",
    "windsurf": "windsurf",
    "zed": "zed",
    "vscode": "vscode",
}


def _server_entry(config, project: str, agent_id: str | None = None) -> dict:
    """ECHO_MEMORY_PROJECT is pinned explicitly rather than left to cwd
    detection: a project-scoped install is a statement about which project this
    is, and an agent launched from a subdirectory or a different shell
    shouldn't be able to file its facts somewhere else.

    `agent_id` identifies the *client*, not the user's shell. Passing None
    falls back to `config.agent_id`, which is only correct when the caller has
    no better information."""
    env = {
        "ECHO_MEMORY_USER_ID": config.user_id,
        "ECHO_MEMORY_AGENT_ID": agent_id or config.agent_id,
        "ECHO_MEMORY_PROJECT": project,
        # Every client shares one private store even though each reports a
        # different agent_id. Without this, giving clients distinct ids - the
        # whole point of doing so - would fork `solo` into one invisible store
        # per client. See Config.solo_key.
        "ECHO_MEMORY_SOLO_KEY": config.solo_key or config.agent_id,
    }
    # Point at the credential rather than embedding it, when one is configured.
    # These files are committable and several sync to a cloud backup; the URL
    # carries a password.
    url_file = os.environ.get("ECHO_MEMORY_DATABASE_URL_FILE")
    if url_file:
        env["ECHO_MEMORY_DATABASE_URL_FILE"] = url_file
    else:
        env["ECHO_MEMORY_DATABASE_URL"] = config.database_url
    return {
        "command": sys.executable,
        "args": ["-m", "echo_memory.server"],
        "env": env,
    }


def _merge_json(path: Path, key_path: tuple[str, ...], value: dict) -> str:
    """Insert value at key_path in a JSON file, preserving everything else.
    Returns "created", "updated" or "unchanged"."""
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except ValueError as e:
            raise ValueError(f"{path} is not valid JSON, refusing to overwrite it: {e}") from e
        except PermissionError as e:
            raise PermissionError(f"cannot read {path}: {e}") from e

    cursor = existing
    for key in key_path[:-1]:
        cursor = cursor.setdefault(key, {})
    was = cursor.get(key_path[-1])
    if was == value:
        return "unchanged"
    cursor[key_path[-1]] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(existing, indent=2) + "\n")
    return "updated" if was is not None else "created"


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then os.replace onto the
    target - which is atomic on POSIX and Windows.

    A plain write_text truncates before it writes, so a process killed between
    the two leaves a zero-length config. Under a project-scoped install that is
    a `git checkout` away. These same helpers now write machine-global files
    like ~/.claude.json, which are under no version control at all, and a
    truncated one costs the user every MCP server they have in every project."""
    tmp = path.with_name(f".{path.name}.echo-mem.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# Codex reads AGENTS.md and has no hook system, so this file is the only place
# it can be told when to use the tools it already has. Measured 2026-09-03: a
# Codex session with all four tools connected and no instruction anywhere spent
# 32 minutes analysing a repo and made zero calls - 0.01s of CPU across the
# whole window. Claude Code gets the same message four ways (SessionStart
# injection, prompt-time recall, the Stop gate, SKILL.md); Codex was getting it
# none.
AGENTS_MARKER = "<!-- echo-memory -->"
AGENTS_END = "<!-- /echo-memory -->"

AGENTS_SECTION = """{marker}
## Echo Memory

This project has persistent memory across sessions and tools, over MCP.

- Call `query_memory` before asking about anything that may already have been
  explained - a past session or a different tool may have recorded it.
- Call `write_episode` in the same turn something worth keeping happens: a
  decision, a correction, a stated preference, a hard-won finding and why it
  holds. Do not batch it to the end; a missed memory costs more than an extra
  call.
- If a recalled fact saved re-explaining something another tool wrote, call
  `record_recall_save` with its fact_id.

You extract the entities and facts yourself - the server never calls a model,
which is why writing is free.
{end}"""

CURSOR_RULE = """---
description: How to use Echo Memory in this project
alwaysApply: true
---

{skill}
"""


def install(root: Path, config, targets: tuple[str, ...], project: str | None = None) -> list[str]:
    root = root.resolve()
    project = project or detect_project(str(root), env={})
    done = []

    if "claude" in targets:
        skill_path = root / SKILL_DIR / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        text = skill_text()
        state = "unchanged" if skill_path.exists() and skill_path.read_text() == text else (
            "updated" if skill_path.exists() else "created"
        )
        skill_path.write_text(text)
        done.append(f"{state}  {skill_path.relative_to(root)}")

        mcp = root / ".mcp.json"
        entry = _server_entry(config, project, CLIENT_AGENT_IDS["claude"])
        state = _merge_json(mcp, ("mcpServers", SERVER_KEY), entry)
        done.append(f"{state}  {mcp.relative_to(root)}")

    if "codex" in targets:
        # Merged into any existing AGENTS.md rather than written over it: the
        # file usually holds the project's own conventions, and replacing those
        # to add a memory section would be a rude way to install anything.
        agents = root / "AGENTS.md"
        section = AGENTS_SECTION.format(marker=AGENTS_MARKER, end=AGENTS_END)
        existing = agents.read_text() if agents.exists() else ""
        if AGENTS_MARKER in existing:
            start = existing.index(AGENTS_MARKER)
            stop = existing.index(AGENTS_END) + len(AGENTS_END)
            body = existing[:start] + section + existing[stop:]
            state = "unchanged" if body == existing else "updated"
        else:
            body = (existing.rstrip("\n") + "\n\n" if existing else "") + section + "\n"
            state = "updated" if existing else "created"
        if state != "unchanged":
            _atomic_write(agents, body)
        done.append(f"{state}  {agents.relative_to(root)}")

    if "cursor" in targets:
        mcp = root / ".cursor" / "mcp.json"
        entry = _server_entry(config, project, CLIENT_AGENT_IDS["cursor"])
        state = _merge_json(mcp, ("mcpServers", SERVER_KEY), entry)
        done.append(f"{state}  {mcp.relative_to(root)}")

        # Cursor has no skills; a project rule with alwaysApply is the nearest
        # equivalent, so it gets the same text rather than a thinner summary.
        rule = root / ".cursor" / "rules" / "echo-memory.mdc"
        rule.parent.mkdir(parents=True, exist_ok=True)
        body = CURSOR_RULE.format(skill=_strip_frontmatter(skill_text()))
        state = "unchanged" if rule.exists() and rule.read_text() == body else (
            "updated" if rule.exists() else "created"
        )
        rule.write_text(body)
        done.append(f"{state}  {rule.relative_to(root)}")

    return done


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text[end + 4 :].lstrip("\n") if end != -1 else text


def render_install(root: Path, project: str, targets: tuple[str, ...], done: list[str]) -> str:
    lines = [
        f"Echo Memory installed for project '{project}' in {root}",
        f"  targets: {', '.join(targets)}",
        "",
    ]
    lines += [f"  {d}" for d in done]
    lines += [
        "",
        (
            "Every fact written from here is attributed to this project. "
            + (
                "These files reference the connection string by path, not by value, "
                "so they carry no credential and are safe to commit."
                if os.environ.get("ECHO_MEMORY_DATABASE_URL_FILE")
                else "These files contain your database URL, password included - "
                "gitignore them, or set ECHO_MEMORY_DATABASE_URL_FILE to keep the "
                "credential out of them."
            )
        ),
    ]
    if "claude" in targets:
        lines.append("Claude Code picks up .mcp.json and the skill on the next session here.")
    if "codex" in targets:
        # Merged into any existing AGENTS.md rather than written over it: the
        # file usually holds the project's own conventions, and replacing those
        # to add a memory section would be a rude way to install anything.
        agents = root / "AGENTS.md"
        section = AGENTS_SECTION.format(marker=AGENTS_MARKER, end=AGENTS_END)
        existing = agents.read_text() if agents.exists() else ""
        if AGENTS_MARKER in existing:
            start = existing.index(AGENTS_MARKER)
            stop = existing.index(AGENTS_END) + len(AGENTS_END)
            body = existing[:start] + section + existing[stop:]
            state = "unchanged" if body == existing else "updated"
        else:
            body = (existing.rstrip("\n") + "\n\n" if existing else "") + section + "\n"
            state = "updated" if existing else "created"
        if state != "unchanged":
            _atomic_write(agents, body)
        done.append(f"{state}  {agents.relative_to(root)}")

    if "cursor" in targets:
        lines.append("Cursor: enable the server under Settings > MCP, then reload the window.")
    return "\n".join(lines) + "\n"
