"""End-to-end tests for the wired-together MCP server (write_episode,
query_memory, get_audit_log sharing one connection pool and scope
resolution). See conftest.py for the migrated_db fixture and
DB-reachability skip.

Calls the @server.tool()-decorated functions directly (confirmed they
remain plain callables, not wrapped) rather than going through a real MCP
client/stdio handshake: that exercises the transport layer, which is the
mcp SDK's responsibility, not this project's.
"""

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.infra.config import Config


def _fresh_server(migrated_db, embedder=None):
    config = Config(user_id="ayush", agent_id="claude-code", database_url=migrated_db)
    server.startup(config=config, embedder=embedder or VectorEmbedder({}))
    return server


def test_write_query_audit_round_trip(migrated_db):
    s = _fresh_server(
        migrated_db,
        VectorEmbedder(
            {
                "Postgres": REFERENCE,
                "Decision": REFERENCE,
                "decided to use Postgres for storage": REFERENCE,
            }
        ),
    )

    write_result = s.write_episode(
        "solo",
        "sess-1",
        [{"name": "Postgres", "type": "tool"}, {"name": "Decision", "type": "decision"}],
        [
            {
                "source": "Decision",
                "target": "Postgres",
                "relation_type": "uses",
                "fact": "decided to use Postgres for storage",
                "confidence": "extracted",
            }
        ],
    )
    assert len(write_result["edges_created"]) == 1

    query_result = s.query_memory("solo", "decided to use Postgres for storage", 10)
    assert len(query_result["facts"]) == 1

    audit_result = s.get_audit_log("solo")
    assert len(audit_result["entries"]) >= 1


def test_solo_and_shared_scopes_are_isolated(migrated_db):
    s = _fresh_server(
        migrated_db,
        VectorEmbedder({"A": REFERENCE, "B": REFERENCE, "solo-only fact": REFERENCE}),
    )

    s.write_episode(
        "solo",
        "sess-1",
        [{"name": "A", "type": "tool"}, {"name": "B", "type": "tool"}],
        [
            {
                "source": "A",
                "target": "B",
                "relation_type": "uses",
                "fact": "solo-only fact",
                "confidence": "extracted",
            }
        ],
    )

    solo_result = s.query_memory("solo", "solo-only fact", 10)
    shared_result = s.query_memory("shared", "solo-only fact", 10)

    assert len(solo_result["facts"]) == 1
    assert shared_result["facts"] == []


def test_invalid_scope_returns_typed_error_not_exception(migrated_db):
    s = _fresh_server(migrated_db)

    assert "error" in s.write_episode("org", "s1", [], [])
    assert "error" in s.query_memory("org", "x", 10)
    assert "error" in s.get_audit_log("org")


def test_different_agents_get_different_solo_scopes(migrated_db):
    config_a = Config(user_id="ayush", agent_id="claude-code", database_url=migrated_db)
    embedder = VectorEmbedder({"A": REFERENCE, "B": REFERENCE, "claude-code's fact": REFERENCE})
    server.startup(config=config_a, embedder=embedder)
    server.write_episode(
        "solo",
        "s1",
        [{"name": "A", "type": "tool"}, {"name": "B", "type": "tool"}],
        [
            {
                "source": "A",
                "target": "B",
                "relation_type": "uses",
                "fact": "claude-code's fact",
                "confidence": "extracted",
            }
        ],
    )

    config_b = Config(user_id="ayush", agent_id="cursor", database_url=migrated_db)
    server.startup(config=config_b, embedder=embedder)
    result = server.query_memory("solo", "claude-code's fact", 10)

    assert result["facts"] == [], "a different agent's solo scope must not see this data"
