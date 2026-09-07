"""A fact with no agent_id is a different failure from a fact that isn't there.

Thirty facts in the author's own store carry no `agent_id` key. They were
written by a long-lived MCP server process that imported this package before
`agent_id` existed on 2026-08-23 and kept running until 2026-09-03; Apache AGE
drops a null-valued property at CREATE, so the key is absent rather than null,
which is why migration 0007's `WHERE e.agent_id = 'unknown'` never matched them.

Until 2026-09-07 `record_recall_save` answered such a fact with "no fact <id>
in this scope - pass the fact_id from a query_memory result, not a remembered
one". The id HAD come from query_memory, so that advice cannot be followed:
the agent re-queries, gets the same id, and tries again.

These tests pin the three things that close it - the distinct read, the
actionable error, and the refusal to write another one."""

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.infra.config import Config
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.ingestion.write_episode import ValidationError, write_episode

FACT = "a fact whose writer was never recorded"


def _serve(migrated_db, agent_id="claude-code"):
    config = Config(
        user_id="ayush", agent_id=agent_id, database_url=migrated_db, project="echo-mem"
    )
    server.startup(config=config, embedder=VectorEmbedder({"probe": REFERENCE, FACT: REFERENCE}))
    return config


def _write_fact():
    result = server.write_episode(
        "shared", "session-1",
        [{"name": "probe", "type": "test"}],
        [{"source": "probe", "target": "probe", "relation_type": "is",
          "fact": FACT, "confidence": "extracted"}],
        entity_resolutions={"probe": {"resolved_to": "new"}},
    )
    return result["edges_created"][0]


def _strip_agent_id(conn, edge_id):
    """Reproduce what the stale server wrote: the key absent, not null."""
    conn.execute("LOAD 'age'")
    conn.execute('SET search_path = ag_catalog, "$user", public')
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->() WHERE id(e) = {int(edge_id)}
            REMOVE e.agent_id
            RETURN id(e)
        $$) AS (n agtype)"""
    )


def test_an_unattributed_fact_is_not_reported_as_missing(migrated_db):
    """The bug itself: a real fact answered as though the id were wrong."""
    _serve(migrated_db)
    edge_id = _write_fact()
    with server._state.pool.connection() as conn:
        _strip_agent_id(conn, edge_id)

    result = server.record_recall_save("shared", str(edge_id), "a note")

    assert "error" in result
    assert "no fact" not in result["error"], (
        "an existing fact must not be described as absent - the agent would "
        "re-query, get the same id back, and loop"
    )


def test_the_error_names_the_real_problem_and_a_way_out(migrated_db):
    _serve(migrated_db)
    edge_id = _write_fact()
    with server._state.pool.connection() as conn:
        _strip_agent_id(conn, edge_id)

    error = server.record_recall_save("shared", str(edge_id), "a note")["error"]

    assert "agent_id" in error
    assert "alembic upgrade head" in error, "the fix has to be named, not implied"


def test_a_genuinely_absent_fact_still_says_so(migrated_db):
    """The other half: telling them apart must not blur the real 404."""
    _serve(migrated_db)
    error = server.record_recall_save("shared", "999999999999", "a note")["error"]
    assert "no fact" in error


def test_an_unattributed_fact_cannot_evidence_a_cross_tool_save(migrated_db):
    """The reason this matters. Left alone, written_by would be neither the
    reader's id nor UNKNOWN_AGENT, so `written_by != recalled_by` would hold
    and the gate would count a save nobody can substantiate."""
    _serve(migrated_db, agent_id="cursor")
    edge_id = _write_fact()
    with server._state.pool.connection() as conn:
        _strip_agent_id(conn, edge_id)

    result = server.record_recall_save("shared", str(edge_id), "a note")

    assert "error" in result
    assert not result.get("cross_tool"), "an unattributable fact must never count"


def test_writing_a_fact_without_an_agent_id_is_refused(migrated_db):
    """AGE drops a null property silently, so nothing downstream would notice.
    The write has to fail where the value is lost."""
    config = _serve(migrated_db)
    with server._state.pool.connection() as conn:
        result = write_episode(
            conn, config.shared_group_id(), "session-2",
            [{"name": "probe", "type": "test"}],
            [{"source": "probe", "target": "probe", "relation_type": "is",
              "fact": FACT, "confidence": "extracted"}],
            {"probe": {"resolved_to": "new"}},
            server._state.embedder,
            project="echo-mem", agent_id=None,
        )
    assert "error" in result
    assert "agent_id" in result["error"]


def test_the_refusal_reaches_the_one_place_the_value_is_lost(migrated_db):
    """Defence in depth: the guard on the CREATE itself, not just the entry
    point, since a future caller could reach _create_edge another way."""
    from echo_memory.ingestion import write_episode as module

    _serve(migrated_db)
    with (
        server._state.pool.connection() as conn,
        pytest.raises(ValidationError, match="agent_id"),
    ):
        module._create_edge(
                conn, "user:ayush:shared", "1", "2",
                {"relation_type": "is", "fact": FACT, "confidence": "extracted"},
                "session-3", "episode-1", 0, server._state.embedder,
                "echo-mem", "",
            )
