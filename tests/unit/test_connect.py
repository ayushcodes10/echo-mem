"""Pointing every tool on a machine at the hosted service.

The self-hosted path needs Docker and a Postgres with Apache AGE, which is the
right default for a tool promising your memory never leaves your machine, and a
lot to ask of somebody still deciding whether the idea is any good. This is the
other door.

Every test here uses a temporary home. Writing to a real one is not
hypothetical: exercising this against `Path.home()` during development replaced
a working Claude Desktop entry with a test key, and the config it overwrote had
to be reconstructed from memory rather than restored.
"""

from __future__ import annotations

import json

import pytest

from echo_memory.cli import connect as connect_cmd

KEY = "em_live_abcdef0123456789"


@pytest.fixture()
def home(tmp_path):
    """A machine with Claude Desktop and Cursor on it, and nothing real."""
    (tmp_path / "Library/Application Support/Claude").mkdir(parents=True)
    (tmp_path / ".cursor").mkdir()
    return tmp_path


def _read(path):
    return json.loads(path.read_text())


def test_a_key_that_is_not_a_key_is_refused_before_anything_is_written(home):
    """A typo reaches the client as an authentication error that says nothing
    about which of several files is wrong."""
    with pytest.raises(connect_cmd.ConnectError) as e:
        connect_cmd.connect("sk-not-ours", home)

    assert "does not look like" in str(e.value)
    assert not (home / ".cursor/mcp.json").exists(), "it wrote a config for a bad key"


def test_no_key_says_where_to_get_one(home):
    with pytest.raises(connect_cmd.ConnectError) as e:
        connect_cmd.connect("", home)

    assert "api.echo-mem.com" in str(e.value)


def test_it_writes_http_and_bearer_not_a_local_process(home):
    """The whole point: connected this way there is no database, no container
    and no local state. A config carrying a database URL would mean there is."""
    connect_cmd.connect(KEY, home)

    entry = _read(home / ".cursor/mcp.json")["mcpServers"]["echo-memory"]
    assert entry["type"] == "http"
    assert entry["url"] == "https://api.echo-mem.com/mcp"
    assert entry["headers"]["Authorization"] == f"Bearer {KEY}"
    assert "command" not in entry and "env" not in entry


def test_other_mcp_servers_are_left_alone(home):
    """These files belong to the user's editor. Rewriting one wholesale removes
    every other server they have registered, which is worse than not being
    installed at all."""
    path = home / ".cursor/mcp.json"
    path.write_text(json.dumps({"mcpServers": {"postgres": {"command": "other"}}}))

    connect_cmd.connect(KEY, home)

    servers = _read(path)["mcpServers"]
    assert servers["postgres"] == {"command": "other"}
    assert "echo-memory" in servers


def test_reconnecting_replaces_rather_than_duplicates(home):
    connect_cmd.connect(KEY, home)
    result = connect_cmd.connect("em_live_9999999999999999", home)

    assert all(w["action"] == "replaced" for w in result["written"])
    entry = _read(home / ".cursor/mcp.json")["mcpServers"]["echo-memory"]
    assert entry["headers"]["Authorization"].endswith("9999999999999999")


def test_absent_clients_get_no_files(tmp_path):
    """Creating Cursor's config on a machine with no Cursor leaves a file
    nobody asked for, and "installed into 4 tools" on a machine with one is a
    lie the next person has to debug."""
    result = connect_cmd.connect(KEY, tmp_path)

    assert result["written"] == []
    assert not (tmp_path / ".cursor").exists()


def test_a_broken_config_is_reported_not_overwritten(home):
    """Hand-edited JSON with a trailing comma is common. Replacing it would
    silently delete whatever the user was in the middle of writing."""
    path = home / ".cursor/mcp.json"
    path.write_text('{"mcpServers": {,}}')

    with pytest.raises(connect_cmd.ConnectError) as e:
        connect_cmd.connect(KEY, home)

    assert "not valid JSON" in str(e.value)
    assert path.read_text() == '{"mcpServers": {,}}'


def test_a_different_deployment_can_be_named(home):
    """Self-hosters of the cloud service exist, and hardcoding one hostname
    would make this command useless to them."""
    connect_cmd.connect(KEY, home, endpoint="https://memory.internal.acme/")

    entry = _read(home / ".cursor/mcp.json")["mcpServers"]["echo-memory"]
    assert entry["url"] == "https://memory.internal.acme/mcp"


def test_the_output_names_the_restart_and_claude_codes_own_door(home):
    result = connect_cmd.connect(KEY, home)
    out = connect_cmd.render(result)

    assert "claude mcp add" in out
    assert "restart" in out.lower()
    assert "no\nlocal database" in out  # the line wraps; the claim is what matters
