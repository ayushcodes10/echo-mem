import pytest

from echo_memory.infra.config import Config, ConfigError, load_config


def test_load_config_reads_required_vars():
    env = {
        "ECHO_MEMORY_USER_ID": "ayush",
        "ECHO_MEMORY_AGENT_ID": "claude-code",
        "ECHO_MEMORY_DATABASE_URL": "postgresql://localhost/echo_memory",
    }
    config = load_config(env)
    assert config.user_id == "ayush"
    assert config.agent_id == "claude-code"
    assert config.database_url == "postgresql://localhost/echo_memory"


@pytest.mark.parametrize(
    "missing",
    ["ECHO_MEMORY_USER_ID", "ECHO_MEMORY_AGENT_ID", "ECHO_MEMORY_DATABASE_URL"],
)
def test_load_config_raises_on_missing_var(missing):
    env = {
        "ECHO_MEMORY_USER_ID": "ayush",
        "ECHO_MEMORY_AGENT_ID": "claude-code",
        "ECHO_MEMORY_DATABASE_URL": "postgresql://localhost/echo_memory",
    }
    del env[missing]
    with pytest.raises(ConfigError, match=missing):
        load_config(env)


def test_solo_and_shared_group_ids_differ_per_agent():
    config = load_config(
        {
            "ECHO_MEMORY_USER_ID": "ayush",
            "ECHO_MEMORY_AGENT_ID": "claude-code",
            "ECHO_MEMORY_DATABASE_URL": "postgresql://localhost/echo_memory",
        }
    )
    other_agent = load_config(
        {
            "ECHO_MEMORY_USER_ID": "ayush",
            "ECHO_MEMORY_AGENT_ID": "cursor",
            "ECHO_MEMORY_DATABASE_URL": "postgresql://localhost/echo_memory",
        }
    )
    assert config.solo_group_id() != other_agent.solo_group_id()
    assert config.shared_group_id() == other_agent.shared_group_id()


def test_group_id_rejects_unknown_scope():
    config = load_config(
        {
            "ECHO_MEMORY_USER_ID": "ayush",
            "ECHO_MEMORY_AGENT_ID": "claude-code",
            "ECHO_MEMORY_DATABASE_URL": "postgresql://localhost/echo_memory",
        }
    )
    with pytest.raises(ConfigError):
        config.group_id("org")


def test_solo_key_separates_attribution_from_tenancy():
    """`adopt` gives each client its own agent_id so cross-tool recall can be
    seen. Without solo_key that would also fork `solo` into one invisible store
    per client, and every reader derives its group ids from its own Config - so
    five of six would vanish from `trial check`, `status` and the dashboard."""
    shared_key = "ayush-desktop"
    configs = [
        Config(user_id="ayush", agent_id=a, database_url="x", solo_key=shared_key)
        for a in ("claude-code", "cursor", "claude-desktop")
    ]

    assert len({c.shared_group_id() for c in configs}) == 1
    assert len({c.solo_group_id() for c in configs}) == 1, "solo must not fork per client"
    assert len({c.agent_id for c in configs}) == 3, "attribution must still differ"


def test_solo_key_defaults_to_agent_id_so_existing_installs_do_not_move():
    without = Config(user_id="ayush", agent_id="claude-code", database_url="x")

    assert without.solo_group_id() == "user:ayush:agent:claude-code"


def test_database_url_can_come_from_a_file(tmp_path):
    """The URL carries a password. `adopt` would write it into six
    machine-global files, several cloud-synced by default, and Claude Desktop
    launched from Finder inherits no shell environment - so a file the config
    points at is the only mechanism that works for every client."""
    secret = tmp_path / "database-url"
    secret.write_text("postgresql://postgres:s3cret@localhost:5433/echo_memory\n")

    config = load_config({
        "ECHO_MEMORY_USER_ID": "ayush",
        "ECHO_MEMORY_AGENT_ID": "claude-code",
        "ECHO_MEMORY_DATABASE_URL_FILE": str(secret),
    })

    assert config.database_url == "postgresql://postgres:s3cret@localhost:5433/echo_memory"


def test_an_unreadable_url_file_is_a_named_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config({
            "ECHO_MEMORY_USER_ID": "ayush",
            "ECHO_MEMORY_AGENT_ID": "claude-code",
            "ECHO_MEMORY_DATABASE_URL_FILE": str(tmp_path / "absent"),
        })


def test_an_empty_url_file_is_a_named_error(tmp_path):
    empty = tmp_path / "database-url"
    empty.write_text("   \n")

    with pytest.raises(ConfigError, match="is empty"):
        load_config({
            "ECHO_MEMORY_USER_ID": "ayush",
            "ECHO_MEMORY_AGENT_ID": "claude-code",
            "ECHO_MEMORY_DATABASE_URL_FILE": str(empty),
        })
