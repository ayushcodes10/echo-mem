"""The measurement has to see the facts it is measuring.

`unattributed_facts` counted only `agent_id = 'unknown'`, the literal string
migration 0003 backfilled. A fact written with no agent_id at all is a
different shape: Apache AGE drops a null-valued property at CREATE, so the key
is absent rather than null, and an equality test against 'unknown' never
matches it.

Thirty such facts sat in the author's own store while `echo-memory health`
reported "every fact has a recorded author" and the criterion 6 gate's
`unattributed == 0` condition passed. A blind spot in the tool built to do the
measuring is worse than no measurement: it reads as a clean bill of health.

`IS NULL` in AGE matches an absent key as well as a null value, so one clause
covers both shapes."""

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.infra.config import Config
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.trial.check import unattributed_facts

FACT = "a fact whose writer was never recorded"


def _serve(migrated_db, agent_id="claude-code"):
    config = Config(
        user_id="ayush", agent_id=agent_id, database_url=migrated_db, project="echo-mem"
    )
    server.startup(config=config, embedder=VectorEmbedder({"probe": REFERENCE, FACT: REFERENCE}))
    return config


def _write_fact(session_id="session-1"):
    result = server.write_episode(
        "shared", session_id,
        [{"name": "probe", "type": "test"}],
        [{"source": "probe", "target": "probe", "relation_type": "is",
          "fact": FACT, "confidence": "extracted"}],
        entity_resolutions={"probe": {"resolved_to": "new"}},
    )
    return result["edges_created"][0]


def _set_agent(conn, edge_id, value):
    """`value=None` removes the key, reproducing what a pre-agent_id server
    wrote; a string sets it, reproducing the 0003 placeholder."""
    conn.execute("LOAD 'age'")
    conn.execute('SET search_path = ag_catalog, "$user", public')
    clause = "REMOVE e.agent_id" if value is None else f"SET e.agent_id = '{value}'"
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->() WHERE id(e) = {int(edge_id)}
            {clause}
            RETURN id(e)
        $$) AS (n agtype)"""
    )


def test_a_fact_with_no_agent_id_key_is_counted(migrated_db):
    """The bug: absent is not the same as 'unknown', and only one was counted."""
    config = _serve(migrated_db)
    edge_id = _write_fact()
    with server._state.pool.connection() as conn:
        _set_agent(conn, edge_id, None)
        assert unattributed_facts(conn, [config.shared_group_id()]) == 1


def test_the_placeholder_is_still_counted(migrated_db):
    """Broadening the query must not lose the shape it already caught."""
    config = _serve(migrated_db)
    edge_id = _write_fact()
    with server._state.pool.connection() as conn:
        _set_agent(conn, edge_id, "unknown")
        assert unattributed_facts(conn, [config.shared_group_id()]) == 1


def test_an_attributed_fact_is_not_counted(migrated_db):
    """The other direction: a real author must never be called unattributed."""
    config = _serve(migrated_db)
    _write_fact()
    with server._state.pool.connection() as conn:
        assert unattributed_facts(conn, [config.shared_group_id()]) == 0


def test_health_does_not_claim_an_author_that_is_not_there(migrated_db):
    """What the user actually saw: a green line over a store with 30 unattributable
    facts."""
    from echo_memory.cli import health

    config = _serve(migrated_db)
    edge_id = _write_fact()
    with server._state.pool.connection() as conn:
        _set_agent(conn, edge_id, None)
        report = health.collect(conn, config)

    assert report["unattributed_facts"] == 1
    assert "every fact has a recorded author" not in health.render(report)


def test_a_missing_author_is_not_reported_as_a_tool_named_None(migrated_db):
    """str(None) is "None", and it was printed as though a tool were called
    that."""
    from echo_memory.cli import health

    config = _serve(migrated_db)
    edge_id = _write_fact()
    with server._state.pool.connection() as conn:
        _set_agent(conn, edge_id, None)
        report = health.collect(conn, config)

    assert "None" not in report["writers"], report["writers"]
    assert "unknown" in report["writers"]
