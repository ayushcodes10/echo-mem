import pytest

from echo_memory.infra.config import ConfigError, load_config


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
