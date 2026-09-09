"""A caller-supplied node id has to be a real node in the caller's own scope.

`entity_resolutions[name]["resolved_to"]` is how an agent answers "which of
these candidates did you mean". Until 2026-09-09 it was taken entirely on trust:
no check that the id existed, that it was a Node, or that it belonged to the
group being written to.

Two failures came out of that, and this file pins both.

The first is the bad-merge class the trial has two confirmed instances of. An id
recalled from an earlier turn rather than read from the current call's
candidates pointed at 'node_embedding table' and 'AGE graphid column type', so
three facts about Indian tax compliance were attached to an embedding table's
lesson. Nothing objected; the facts simply landed somewhere else, and it was
found only by querying where the edges had gone.

The second is worse and only exists once the engine is hosted. Demonstrated
against a real database before the fix: one account passed another account's
node id and successfully attached an edge to it, because the edge MATCH found
nodes by id with no group filter. The edge carried the writer's own group_id
while pointing at somebody else's entity.
"""

from __future__ import annotations

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import write_episode

ALICE = "acct:alice:shared"
BOB = "acct:bob:shared"

SECRET = "alice's private project"
GRAFT = "bob attached this to alice's node"


def _embedder():
    return VectorEmbedder({
        "Alice Project": REFERENCE, "Bob Thing": REFERENCE,
        SECRET: REFERENCE, GRAFT: REFERENCE,
    })


def _seed_alice(conn):
    result = write_episode(
        conn, ALICE, "s1",
        [{"name": "Alice Project", "type": "project"}],
        [{"source": "Alice Project", "target": "Alice Project", "relation_type": "is",
          "fact": SECRET, "confidence": "extracted"}],
        {"Alice Project": {"resolved_to": "new"}},
        _embedder(), agent_id="claude-code",
    )
    assert result.get("edges_created"), result
    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE n.name = 'Alice Project' RETURN id(n)
        $$) AS (i agtype)"""
    ).fetchone()
    return str(row[0])


def _bob_writes_at(conn, node_id):
    return write_episode(
        conn, BOB, "s2",
        [{"name": "Alice Project", "type": "project"}, {"name": "Bob Thing", "type": "thing"}],
        [{"source": "Bob Thing", "target": "Alice Project", "relation_type": "relates_to",
          "fact": GRAFT, "confidence": "extracted"}],
        {"Alice Project": {"resolved_to": node_id}, "Bob Thing": {"resolved_to": "new"}},
        _embedder(), agent_id="cursor",
    )


def test_one_scope_cannot_attach_an_edge_to_anothers_node(migrated_db):
    """The cross-tenant write. This passed before the fix."""
    with connect(migrated_db) as conn:
        alice_node = _seed_alice(conn)
        result = _bob_writes_at(conn, alice_node)

        assert "error" in result, result
        assert not result.get("edges_created")

        landed = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH (a)-[e:FACT]->(b) WHERE id(b) = {int(alice_node)}
                RETURN e.group_id
            $$) AS (g agtype)"""
        ).fetchall()

    groups = {str(g[0]).strip('"') for g in landed}
    assert groups == {ALICE}, f"a foreign edge reached Alice's node: {groups}"


def test_an_id_that_is_not_a_node_at_all_is_refused(migrated_db):
    with connect(migrated_db) as conn:
        result = _bob_writes_at(conn, "999999999999")
    assert "error" in result
    assert not result.get("edges_created")


def test_the_error_says_what_to_pass_instead(migrated_db):
    """The bad merge happened because an id was remembered rather than read.
    The message has to name that, or the next caller repeats it."""
    with connect(migrated_db) as conn:
        error = _bob_writes_at(conn, "999999999999")["error"]
    assert "not a node in this scope" in error
    assert "new" in error


def test_a_valid_id_from_the_same_scope_still_resolves(migrated_db):
    """The check must not break the round-trip it protects: answering an
    ambiguity with a candidate id from your own scope is the whole feature."""
    with connect(migrated_db) as conn:
        alice_node = _seed_alice(conn)
        result = write_episode(
            conn, ALICE, "s3",
            [{"name": "Alice Project", "type": "project"}],
            [{"source": "Alice Project", "target": "Alice Project",
              "relation_type": "also_is", "fact": "a second alice fact",
              "confidence": "extracted"}],
            {"Alice Project": {"resolved_to": alice_node}},
            VectorEmbedder({"Alice Project": REFERENCE, "a second alice fact": REFERENCE}),
            agent_id="claude-code",
        )
    assert result.get("edges_created"), result


def test_a_rejected_resolution_writes_nothing_at_all(migrated_db):
    """Raised inside the transaction, so a bad resolved_to loses the whole
    episode rather than attaching some of its facts to the wrong entity."""
    with connect(migrated_db) as conn:
        _seed_alice(conn)
        _bob_writes_at(conn, "999999999999")
        rows = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH (n:Node) WHERE n.name = 'Bob Thing' RETURN id(n)
            $$) AS (i agtype)"""
        ).fetchall()
    assert rows == [], "the rejected episode left a node behind"
