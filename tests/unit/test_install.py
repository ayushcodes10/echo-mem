"""Per-project install: the skill, the MCP entries, and the merge behaviour
that keeps it from trampling a project's existing config."""

import json
from pathlib import Path

import pytest

from echo_memory.cli.install import (
    AGENTS_MARKER,
    _merge_json,
    _strip_frontmatter,
    install,
    render_install,
    skill_text,
)
from echo_memory.infra.config import Config, load_config

CONFIG = Config(
    user_id="ayush", agent_id="claude-code",
    database_url="postgresql://postgres:postgres@localhost:5433/echo_memory",
)


def test_skill_ships_inside_the_package():
    text = skill_text()
    assert text.startswith("---\nname: echo-memory")
    assert "write_episode" in text and "query_memory" in text


def test_skill_states_the_confidence_enum_exactly():
    """A real trial session guessed numeric confidence values and was rejected
    every time, so the skill has to spell the enum out."""
    text = skill_text()
    assert '"extracted"' in text and '"inferred"' in text and '"ambiguous"' in text


def test_claude_install_writes_skill_and_project_mcp(tmp_path):
    project = tmp_path / "my-repo"
    project.mkdir()

    install(project, CONFIG, ("claude",), project="my-repo")

    skill = project / ".claude" / "skills" / "echo-memory" / "SKILL.md"
    assert skill.read_text() == skill_text()
    mcp = json.loads((project / ".mcp.json").read_text())
    assert mcp["mcpServers"]["echo-memory"]["args"] == ["-m", "echo_memory.server"]
    assert mcp["mcpServers"]["echo-memory"]["env"]["ECHO_MEMORY_PROJECT"] == "my-repo"


def test_project_is_pinned_not_left_to_cwd(tmp_path):
    """A project-scoped install is a statement about which project this is; an
    agent launched from a subdirectory must not be able to file facts
    elsewhere."""
    project = tmp_path / "repo"
    project.mkdir()

    install(project, CONFIG, ("claude",), project="pinned-name")

    mcp = json.loads((project / ".mcp.json").read_text())
    assert mcp["mcpServers"]["echo-memory"]["env"]["ECHO_MEMORY_PROJECT"] == "pinned-name"


def test_cursor_install_writes_mcp_and_an_always_applied_rule(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()

    install(project, CONFIG, ("cursor",), project="repo")

    mcp = json.loads((project / ".cursor" / "mcp.json").read_text())
    assert "echo-memory" in mcp["mcpServers"]
    rule = (project / ".cursor" / "rules" / "echo-memory.mdc").read_text()
    assert rule.startswith("---\ndescription: How to use Echo Memory")
    assert "alwaysApply: true" in rule
    # the rule carries the skill's own guidance, not a thinner summary
    assert "Write the moment it happens" in rule
    assert rule.count("name: echo-memory") == 0, "the skill's frontmatter shouldn't leak in"


def test_existing_mcp_servers_are_preserved(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"other-thing": {"command": "node", "args": ["server.js"]}}
    }))

    install(project, CONFIG, ("claude",), project="repo")

    mcp = json.loads((project / ".mcp.json").read_text())
    assert mcp["mcpServers"]["other-thing"]["command"] == "node"
    assert "echo-memory" in mcp["mcpServers"]


def test_unrelated_top_level_keys_are_preserved(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".mcp.json").write_text(json.dumps({"someOtherSetting": {"a": 1}}))

    install(project, CONFIG, ("claude",), project="repo")

    mcp = json.loads((project / ".mcp.json").read_text())
    assert mcp["someOtherSetting"] == {"a": 1}


def test_reinstalling_reports_unchanged(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()

    install(project, CONFIG, ("claude",), project="repo")
    second = install(project, CONFIG, ("claude",), project="repo")

    assert all(line.startswith("unchanged") for line in second), second


def test_malformed_json_is_refused_rather_than_overwritten(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".mcp.json").write_text("{ not json at all")

    with pytest.raises(ValueError, match="refusing to overwrite"):
        install(project, CONFIG, ("claude",), project="repo")

    assert (project / ".mcp.json").read_text() == "{ not json at all"


def test_both_targets_write_both_sets(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()

    install(project, CONFIG, ("claude", "cursor"), project="repo")

    assert (project / ".claude" / "skills" / "echo-memory" / "SKILL.md").exists()
    assert (project / ".mcp.json").exists()
    assert (project / ".cursor" / "mcp.json").exists()
    assert (project / ".cursor" / "rules" / "echo-memory.mdc").exists()


def test_project_name_defaults_to_the_directory(tmp_path):
    project = tmp_path / "inferred-name"
    project.mkdir()

    install(project, CONFIG, ("claude",))

    mcp = json.loads((project / ".mcp.json").read_text())
    assert mcp["mcpServers"]["echo-memory"]["env"]["ECHO_MEMORY_PROJECT"] == "inferred-name"


def test_strip_frontmatter_leaves_body_untouched_when_absent():
    assert _strip_frontmatter("# Title\n\nbody") == "# Title\n\nbody"


def test_each_client_announces_its_own_agent_id(tmp_path):
    """Until 2026-08-28 every client got `config.agent_id`, so Claude Code and
    Cursor both wrote facts tagged claude-code. That made the v1a cross-tool
    criterion (`written_by != recalled_by`) unsatisfiable no matter how well
    recall worked - there was only ever one writer in the data."""
    project = tmp_path / "repo"
    project.mkdir()

    install(project, CONFIG, ("claude", "cursor"), project="repo")

    claude = json.loads((project / ".mcp.json").read_text())
    cursor = json.loads((project / ".cursor" / "mcp.json").read_text())
    claude_id = claude["mcpServers"]["echo-memory"]["env"]["ECHO_MEMORY_AGENT_ID"]
    cursor_id = cursor["mcpServers"]["echo-memory"]["env"]["ECHO_MEMORY_AGENT_ID"]

    assert claude_id == "claude-code"
    assert cursor_id == "cursor"
    assert claude_id != cursor_id, "cross-tool recall is undetectable if clients share an id"


def test_a_config_is_never_left_truncated(tmp_path, monkeypatch):
    """write_text truncates before it writes. These helpers also write
    machine-global files under no version control, where a half-written
    ~/.claude.json costs the user every MCP server they have."""
    target = tmp_path / "mcp.json"
    target.write_text('{"mcpServers": {"other": {"command": "keep-me"}}}')

    real_write = Path.write_text

    def explode(self, text, *a, **kw):
        if self.name.endswith(".tmp"):
            raise KeyboardInterrupt("killed mid-write")
        return real_write(self, text, *a, **kw)

    monkeypatch.setattr(Path, "write_text", explode)
    with pytest.raises(KeyboardInterrupt):
        _merge_json(target, ("mcpServers", "echo-memory"), {"command": "x"})
    monkeypatch.undo()

    assert json.loads(target.read_text())["mcpServers"]["other"]["command"] == "keep-me"
    assert not list(tmp_path.glob(".*echo-mem.tmp")), "temp file left behind"


def test_clients_share_one_solo_store_while_reporting_different_agents(tmp_path):
    """The round trip that F1 fails: rebuild a Config from each written entry's
    env and assert the group ids agree. Distinct agent_ids are the point of
    adopt; distinct SOLO stores would be an invisible regression."""
    project = tmp_path / "repo"
    project.mkdir()

    install(project, CONFIG, ("claude", "cursor"), project="repo")

    envs = [
        json.loads((project / p).read_text())["mcpServers"]["echo-memory"]["env"]
        for p in (".mcp.json", ".cursor/mcp.json")
    ]
    configs = [load_config(e) for e in envs]

    assert len({c.agent_id for c in configs}) == 2, "attribution must differ"
    assert len({c.shared_group_id() for c in configs}) == 1
    assert len({c.solo_group_id() for c in configs}) == 1, "solo must not fork per client"


def test_a_configured_credential_file_is_referenced_not_embedded(tmp_path, monkeypatch):
    secret = tmp_path / "database-url"
    secret.write_text("postgresql://postgres:s3cret@localhost:5433/echo_memory\n")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL_FILE", str(secret))
    project = tmp_path / "repo"
    project.mkdir()

    done = install(project, CONFIG, ("claude",), project="repo")

    written = (project / ".mcp.json").read_text()
    assert "s3cret" not in written, "the password must not reach a committable file"
    assert "ECHO_MEMORY_DATABASE_URL_FILE" in written
    assert done is not None


def test_without_a_credential_file_the_message_says_gitignore_not_commit(tmp_path):
    """The old message told users to commit a file containing their password."""
    project = tmp_path / "repo"
    project.mkdir()
    done = install(project, CONFIG, ("claude",), project="repo")

    text = render_install(project, "repo", ("claude",), done)

    assert "gitignore" in text
    assert "Commit these files" not in text


def _codex_install(root):
    return install(root, CONFIG, ("codex",), project="eigen")


def test_codex_gets_an_instruction_because_it_has_no_hooks(tmp_path):
    """Measured 2026-09-03: a Codex session with all four tools connected and no
    instruction anywhere spent 32 minutes analysing a repo and made zero calls -
    0.01s of CPU across the window. Claude Code is told the same thing four ways
    (SessionStart injection, prompt-time recall, the Stop gate, SKILL.md); Codex
    reads AGENTS.md and was being told none of them."""
    done = _codex_install(tmp_path)

    agents = tmp_path / "AGENTS.md"
    assert agents.exists()
    body = agents.read_text()
    for tool in ("query_memory", "write_episode", "record_recall_save"):
        assert tool in body
    assert any("AGENTS.md" in line for line in done)


def test_an_existing_agents_md_is_kept(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Eigon\n\nRun `make test` before pushing.\n")

    _codex_install(tmp_path)

    body = agents.read_text()
    assert "Run `make test` before pushing." in body
    assert "write_episode" in body


def test_reinstalling_replaces_the_section_instead_of_stacking_it(tmp_path):
    _codex_install(tmp_path)
    once = (tmp_path / "AGENTS.md").read_text()
    _codex_install(tmp_path)
    twice = (tmp_path / "AGENTS.md").read_text()

    assert once == twice
    assert twice.count(AGENTS_MARKER) == 1


def test_a_reinstall_over_edited_project_text_keeps_that_text(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Eigon\n")
    _codex_install(tmp_path)
    agents.write_text(agents.read_text() + "\n## Deploy\n\nUse the harness.\n")

    _codex_install(tmp_path)

    body = agents.read_text()
    assert "Use the harness." in body
    assert "# Eigon" in body
    assert body.count(AGENTS_MARKER) == 1


def test_installing_for_claude_does_not_write_agents_md(tmp_path):
    install(tmp_path, CONFIG, ("claude",), project="eigen")
    assert not (tmp_path / "AGENTS.md").exists()
