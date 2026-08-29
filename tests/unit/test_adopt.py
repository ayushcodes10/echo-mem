"""Machine-wide client adoption.

These files are global and under no version control, so the tests care less
about the happy path than about the four ways adopt could quietly do damage:
writing a key no tool reads, repointing somebody's existing setup, aborting
half-done, and touching the developer's own config while the suite runs."""

import json

import pytest

from echo_memory.cli import adopt
from echo_memory.infra.config import Config, load_config

CONFIG = Config(
    user_id="ayush", agent_id="claude-code",
    database_url="postgresql://postgres:postgres@localhost:5433/echo_memory",
    project="repo",
)


def _home(tmp_path, *clients):
    """A fake home with the named clients' config files present."""
    for name in clients:
        path = adopt.CLIENTS[name]["path"](tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mcpServers": {}}))
    return tmp_path


def test_home_is_injectable_so_tests_never_touch_a_real_config(tmp_path):
    """The whole suite depends on this. One forgotten call site writes to the
    developer's own ~/.claude.json on the first run."""
    results = adopt.plan(CONFIG, home=tmp_path)

    assert all(str(tmp_path) in str(r["path"]) for r in results)


def test_a_client_that_is_not_installed_is_skipped_not_created(tmp_path):
    """Creating a config for a tool the user does not have would report success
    for a client that will never read it."""
    results = adopt.plan(CONFIG, home=_home(tmp_path, "cursor"))

    by_client = {r["client"]: r for r in results}
    assert by_client["cursor"]["action"] == "create"
    assert by_client["claude-code"]["action"] == "skip"
    assert by_client["claude-code"]["why"] == "not installed"


def test_every_client_gets_its_own_agent_id(tmp_path):
    home = _home(tmp_path, "claude-code", "cursor", "claude-desktop")

    adopt.apply(CONFIG, home=home)

    ids = set()
    for name in ("claude-code", "cursor", "claude-desktop"):
        doc = json.loads(adopt.CLIENTS[name]["path"](home).read_text())
        ids.add(doc["mcpServers"]["echo-memory"]["env"]["ECHO_MEMORY_AGENT_ID"])
    assert ids == {"claude-code", "cursor", "claude-desktop"}


def test_adopted_clients_share_one_memory(tmp_path):
    """Distinct agent ids, one graph. Rebuilding a Config from each written
    entry is the round trip that catches a forked solo scope."""
    home = _home(tmp_path, "claude-code", "cursor")

    adopt.apply(CONFIG, home=home)

    configs = []
    for name in ("claude-code", "cursor"):
        doc = json.loads(adopt.CLIENTS[name]["path"](home).read_text())
        configs.append(load_config(doc["mcpServers"]["echo-memory"]["env"]))
    assert len({c.shared_group_id() for c in configs}) == 1
    assert len({c.solo_group_id() for c in configs}) == 1
    assert len({c.agent_id for c in configs}) == 2


def test_a_dry_run_writes_nothing(tmp_path):
    home = _home(tmp_path, "claude-code")
    path = adopt.CLIENTS["claude-code"]["path"](home)
    before, mtime = path.read_text(), path.stat().st_mtime

    adopt.plan(CONFIG, home=home)

    assert path.read_text() == before
    assert path.stat().st_mtime == mtime
    assert not adopt.registry_path(home).exists()


def test_an_entry_pointing_at_another_database_is_not_silently_repointed(tmp_path):
    """Facts would keep being written and simply land in a different graph."""
    home = _home(tmp_path, "cursor")
    path = adopt.CLIENTS["cursor"]["path"](home)
    path.write_text(json.dumps({"mcpServers": {"echo-memory": {
        "command": "python", "args": ["-m", "echo_memory.server"],
        "env": {"ECHO_MEMORY_USER_ID": "ayush",
                "ECHO_MEMORY_DATABASE_URL": "postgresql://elsewhere/other"},
    }}}))

    results = {r["client"]: r for r in adopt.apply(CONFIG, home=home)}

    assert results["cursor"]["action"] == "conflict"
    assert "postgresql://elsewhere/other" in path.read_text(), "must not overwrite"


def test_force_repoints_a_conflicting_entry(tmp_path):
    home = _home(tmp_path, "cursor")
    path = adopt.CLIENTS["cursor"]["path"](home)
    path.write_text(json.dumps({"mcpServers": {"echo-memory": {
        "env": {"ECHO_MEMORY_DATABASE_URL": "postgresql://elsewhere/other"}}}}))

    adopt.apply(CONFIG, home=home, force=True)

    assert "elsewhere" not in path.read_text()


def test_unrelated_servers_and_keys_survive(tmp_path):
    home = _home(tmp_path, "claude-code")
    path = adopt.CLIENTS["claude-code"]["path"](home)
    path.write_text(json.dumps({
        "numStartups": 41,
        "mcpServers": {"other-tool": {"command": "keep-me"}},
    }))

    adopt.apply(CONFIG, home=home)

    doc = json.loads(path.read_text())
    assert doc["numStartups"] == 41
    assert doc["mcpServers"]["other-tool"]["command"] == "keep-me"


def test_a_malformed_config_does_not_abort_the_other_clients(tmp_path):
    """Six targets means six ways to fail. Leaving three wired with no record of
    which is worse than a partial success that says so."""
    home = _home(tmp_path, "claude-code", "cursor")
    adopt.CLIENTS["claude-code"]["path"](home).write_text("{ not json,")

    results = {r["client"]: r for r in adopt.apply(CONFIG, home=home)}

    assert results["claude-code"]["action"] == "failed"
    assert results["cursor"]["action"] == "created"


def test_the_registry_records_wired_clients_so_a_silent_one_is_visible(tmp_path):
    """`status.writers()` counts facts, so an agent that has written nothing
    reads as absent rather than as zero."""
    home = _home(tmp_path, "claude-code", "cursor")

    adopt.apply(CONFIG, home=home)

    wired = {c["agent_id"] for c in adopt.adopted_clients(home)}
    assert wired == {"claude-code", "cursor"}
    assert adopt.registry_path(home).stat().st_mode & 0o777 == 0o600


def test_a_backup_is_written_before_any_change(tmp_path):
    home = _home(tmp_path, "claude-code")

    adopt.apply(CONFIG, home=home)

    backups = list(home.glob(".claude.json.echo-mem-backup-*"))
    assert len(backups) == 1


def test_unsupported_clients_are_named_rather_than_guessed(tmp_path):
    """Zed and VS Code use different key paths and JSONC. Guessing their schema
    is the same mistake as guessing their path: _merge_json would write a key
    neither reads and report success."""
    text = adopt.render(adopt.plan(CONFIG, home=tmp_path), applied=False)

    assert "zed" in text and "unsupported" in text
    assert "vscode" in text
    assert set(adopt.CLIENTS) & set(adopt.UNSUPPORTED) == set()


@pytest.mark.parametrize("action", ["create", "update", "unchanged"])
def test_plan_explains_every_action(tmp_path, action):
    for r in adopt.plan(CONFIG, home=_home(tmp_path, "cursor")):
        assert r["why"], f"{r['client']} has no explanation"


def test_moving_the_credential_into_a_file_is_not_a_conflict(tmp_path, monkeypatch):
    """Found by running adopt against a real machine: the inline URL and the
    path of a file containing that same URL are different strings, so the guard
    read a routine migration as a repoint to another database. It is the case
    _same_target's own docstring predicted and did not handle."""
    secret = tmp_path / "database-url"
    secret.write_text(CONFIG.database_url + "\n")
    home = _home(tmp_path, "cursor")
    path = adopt.CLIENTS["cursor"]["path"](home)
    path.write_text(json.dumps({"mcpServers": {"echo-memory": {
        "env": {"ECHO_MEMORY_USER_ID": "ayush",
                "ECHO_MEMORY_DATABASE_URL": CONFIG.database_url},
    }}}))
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL_FILE", str(secret))

    results = {r["client"]: r for r in adopt.plan(CONFIG, home=home)}

    assert results["cursor"]["action"] == "update", "same database, expressed differently"


def test_a_credential_file_naming_another_database_is_still_a_conflict(tmp_path, monkeypatch):
    secret = tmp_path / "database-url"
    secret.write_text("postgresql://postgres:pw@localhost:5433/somewhere_else\n")
    home = _home(tmp_path, "cursor")
    adopt.CLIENTS["cursor"]["path"](home).write_text(json.dumps({"mcpServers": {
        "echo-memory": {"env": {"ECHO_MEMORY_USER_ID": "ayush",
                                "ECHO_MEMORY_DATABASE_URL": CONFIG.database_url}}}}))
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL_FILE", str(secret))

    results = {r["client"]: r for r in adopt.plan(CONFIG, home=home)}

    assert results["cursor"]["action"] == "conflict"
