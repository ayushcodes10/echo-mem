"""End-to-end tests for write_episode against a real Postgres+AGE+pgvector
database. See conftest.py for the migrated_db fixture and DB-reachability
skip.

Uses the real LocalEmbedder where genuine semantic behavior matters, and the
deterministic VectorEmbedder (fake_embedder.py) where a test needs an exact,
known cosine similarity to hit a specific threshold boundary; a real model's
similarity for arbitrary strings isn't controllable enough for that.
"""

from fake_embedder import REFERENCE, VectorEmbedder, unit_vector_at_angle

from echo_memory.infra.db import connect
from echo_memory.ingestion.embeddings import LocalEmbedder
from echo_memory.ingestion.write_episode import write_episode


def test_new_entities_and_facts_create_nodes_edges_embeddings(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()

    result = write_episode(
        conn,
        "g1",
        "sess-1",
        [{"name": "Postgres", "type": "tool"}, {"name": "AGE decision", "type": "decision"}],
        [
            {
                "source": "AGE decision",
                "target": "Postgres",
                "relation_type": "uses",
                "fact": "decided to use Postgres",
                "confidence": "extracted",
            }
        ],
        {},
        embedder,
    )

    assert result["ambiguous_entities"] == []
    assert len(result["edges_created"]) == 1

    (node_count,) = conn.execute("SELECT count(*) FROM public.node_embedding").fetchone()
    assert node_count == 2
    (edge_count,) = conn.execute("SELECT count(*) FROM public.fact_embedding").fetchone()
    assert edge_count == 1
    (audit_count,) = conn.execute(
        "SELECT count(*) FROM public.audit_entry WHERE mutation_type = 'created'"
    ).fetchone()
    assert audit_count == 1


def test_exact_match_reuses_existing_node_case_insensitive(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()

    write_episode(
        conn,
        "g1",
        "sess-1",
        [{"name": "Postgres", "type": "tool"}, {"name": "AGE decision", "type": "decision"}],
        [
            {
                "source": "AGE decision",
                "target": "Postgres",
                "relation_type": "uses",
                "fact": "decided to use Postgres",
                "confidence": "extracted",
            }
        ],
        {},
        embedder,
    )
    result2 = write_episode(
        conn,
        "g1",
        "sess-2",
        [{"name": "postgres", "type": "tool"}, {"name": "AGE decision", "type": "decision"}],
        [
            {
                "source": "AGE decision",
                "target": "postgres",
                "relation_type": "mentions",
                "fact": "brought up postgres again",
                "confidence": "extracted",
            }
        ],
        {},
        embedder,
    )

    assert result2["ambiguous_entities"] == []
    (node_count,) = conn.execute("SELECT count(*) FROM public.node_embedding").fetchone()
    assert node_count == 2, "exact (case-insensitive) match must not create a duplicate node"
    (resolved_count,) = conn.execute(
        "SELECT count(*) FROM public.audit_entry WHERE mutation_type = 'entity_resolved' "
        "AND resolution_detail = 'exact match'"
    ).fetchone()
    assert resolved_count == 2  # both entities in the second call matched exactly

    (postgres_node_id,) = conn.execute(
        """SELECT * FROM cypher('echo_memory', $$
            MATCH (n:Node {name: 'Postgres'}) RETURN id(n)
        $$) AS (id agtype)"""
    ).fetchone()
    (affected_node_id,) = conn.execute(
        "SELECT affected_node_id FROM public.audit_entry "
        "WHERE mutation_type = 'entity_resolved' LIMIT 1"
    ).fetchone()
    assert str(affected_node_id) == str(postgres_node_id)


def test_fact_superseded_invalidates_old_edge(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()

    entities = [{"name": "Postgres", "type": "tool"}, {"name": "AGE decision", "type": "decision"}]
    fact_template = {
        "source": "AGE decision",
        "target": "Postgres",
        "relation_type": "uses",
        "confidence": "extracted",
    }

    r1 = write_episode(
        conn, "g1", "s1", entities,
        [{**fact_template, "fact": "decided to use Postgres for storage"}], {}, embedder,
    )
    r2 = write_episode(
        conn, "g1", "s2", entities,
        [{**fact_template, "fact": "switched to Postgres for durability"}], {}, embedder,
    )

    old_edge_id, new_edge_id = r1["edges_created"][0], r2["edges_created"][0]
    assert old_edge_id != new_edge_id

    (t_invalid,) = conn.execute(
        f"""SELECT * FROM cypher('echo_memory', $$
            MATCH ()-[e:FACT]->() WHERE id(e) = {old_edge_id}
            RETURN e.t_invalid
        $$) AS (t_invalid agtype)"""
    ).fetchone()
    assert t_invalid is not None

    (superseded_count,) = conn.execute(
        "SELECT count(*) FROM public.audit_entry WHERE mutation_type = 'fact_superseded' "
        "AND %s = ANY(affected_edge_ids) AND %s = ANY(affected_edge_ids)",
        (old_edge_id, new_edge_id),
    ).fetchone()
    assert superseded_count == 1


def test_ambiguous_similarity_defers_and_creates_no_edge(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder({"Postgres": REFERENCE, "Postgres DB": unit_vector_at_angle(0.80)})

    write_episode(
        conn, "g1", "s1",
        [{"name": "Postgres", "type": "tool"}],
        [], {}, embedder,
    )
    result = write_episode(
        conn, "g1", "s2",
        [{"name": "Postgres DB", "type": "tool"}, {"name": "Postgres", "type": "tool"}],
        [
            {
                "source": "Postgres DB",
                "target": "Postgres",
                "relation_type": "mentions",
                "fact": "irrelevant, should be skipped",
                "confidence": "extracted",
            }
        ],
        {},
        embedder,
    )

    assert result["edges_created"] == []
    assert len(result["ambiguous_entities"]) == 1
    ambiguous = result["ambiguous_entities"][0]
    assert ambiguous["mention"] == "Postgres DB"
    assert ambiguous["candidates"][0]["name"] == "Postgres"
    assert 0.79 < ambiguous["candidates"][0]["similarity"] < 0.81

    (node_count,) = conn.execute("SELECT count(*) FROM public.node_embedding").fetchone()
    assert node_count == 1, "an ambiguous mention must not create a node until resolved"


def test_high_similarity_silently_merges_and_appends_alias(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder(
        {
            "Postgres": REFERENCE,
            "postgres-db": unit_vector_at_angle(0.95),
            "self-reference via alias": unit_vector_at_angle(0.5),
        }
    )

    write_episode(conn, "g1", "s1", [{"name": "Postgres", "type": "tool"}], [], {}, embedder)
    result = write_episode(
        conn, "g1", "s2",
        [{"name": "postgres-db", "type": "tool"}, {"name": "Postgres", "type": "tool"}],
        [
            {
                "source": "postgres-db",
                "target": "Postgres",
                "relation_type": "mentions",
                "fact": "self-reference via alias",
                "confidence": "extracted",
            }
        ],
        {},
        embedder,
    )

    assert result["ambiguous_entities"] == []
    assert len(result["edges_created"]) == 1
    (node_count,) = conn.execute("SELECT count(*) FROM public.node_embedding").fetchone()
    assert node_count == 1, "a high-confidence fuzzy match must not create a new node"

    (aliases,) = conn.execute(
        """SELECT * FROM cypher('echo_memory', $$
            MATCH (n:Node {name: 'Postgres'}) RETURN n.aliases
        $$) AS (aliases agtype)"""
    ).fetchone()
    assert "postgres-db" in str(aliases)


def test_entity_resolutions_confirms_ambiguous_match(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder(
        {
            "Postgres": REFERENCE,
            "Postgres DB": unit_vector_at_angle(0.80),
            "confirmed later": unit_vector_at_angle(0.5),
        }
    )

    write_episode(conn, "g1", "s1", [{"name": "Postgres", "type": "tool"}], [], {}, embedder)
    first = write_episode(
        conn, "g1", "s2",
        [{"name": "Postgres DB", "type": "tool"}, {"name": "Postgres", "type": "tool"}],
        [
            {
                "source": "Postgres DB",
                "target": "Postgres",
                "relation_type": "mentions",
                "fact": "confirmed later",
                "confidence": "extracted",
            }
        ],
        {},
        embedder,
    )
    node_id = first["ambiguous_entities"][0]["candidates"][0]["node_id"]

    second = write_episode(
        conn, "g1", "s2",
        [{"name": "Postgres DB", "type": "tool"}, {"name": "Postgres", "type": "tool"}],
        [
            {
                "source": "Postgres DB",
                "target": "Postgres",
                "relation_type": "mentions",
                "fact": "confirmed later",
                "confidence": "extracted",
            }
        ],
        {"Postgres DB": {"resolved_to": node_id, "rationale": "same thing"}},
        embedder,
    )

    assert second["ambiguous_entities"] == []
    assert len(second["edges_created"]) == 1
    (node_count,) = conn.execute("SELECT count(*) FROM public.node_embedding").fetchone()
    assert node_count == 1


def test_entity_resolutions_rejects_as_new(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder(
        {
            "Postgres": REFERENCE,
            "Postgres DB": unit_vector_at_angle(0.80),
            "deferred": unit_vector_at_angle(0.5),
            "actually a different thing": unit_vector_at_angle(0.3),
        }
    )

    write_episode(conn, "g1", "s1", [{"name": "Postgres", "type": "tool"}], [], {}, embedder)
    write_episode(
        conn, "g1", "s2",
        [{"name": "Postgres DB", "type": "tool"}, {"name": "Postgres", "type": "tool"}],
        [
            {
                "source": "Postgres DB",
                "target": "Postgres",
                "relation_type": "mentions",
                "fact": "deferred",
                "confidence": "extracted",
            }
        ],
        {},
        embedder,
    )
    second = write_episode(
        conn, "g1", "s2",
        [{"name": "Postgres DB", "type": "tool"}, {"name": "Postgres", "type": "tool"}],
        [
            {
                "source": "Postgres DB",
                "target": "Postgres",
                "relation_type": "mentions",
                "fact": "actually a different thing",
                "confidence": "extracted",
            }
        ],
        {"Postgres DB": {"resolved_to": "new"}},
        embedder,
    )

    assert len(second["edges_created"]) == 1
    (node_count,) = conn.execute("SELECT count(*) FROM public.node_embedding").fetchone()
    assert node_count == 2, "an explicit 'new' resolution must create its own node"


def test_validation_rejects_bad_confidence(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder({"X": REFERENCE})
    result = write_episode(
        conn, "g1", "s1", [{"name": "X", "type": "tool"}],
        [{"source": "X", "target": "X", "relation_type": "uses", "fact": "f", "confidence": "certain"}],
        {}, embedder,
    )
    assert "error" in result
    assert "confidence" in result["error"]


def test_validation_rejects_fact_referencing_unknown_entity(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder({"X": REFERENCE})
    result = write_episode(
        conn, "g1", "s1", [{"name": "X", "type": "tool"}],
        [{"source": "X", "target": "Y", "relation_type": "uses", "fact": "f", "confidence": "extracted"}],
        {}, embedder,
    )
    assert "error" in result
    assert "not in entities" in result["error"]


def test_validation_rejects_too_many_entities(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder({})
    entities = [{"name": f"e{i}", "type": "tool"} for i in range(51)]
    result = write_episode(conn, "g1", "s1", entities, [], {}, embedder)
    assert "error" in result
    assert "too many entities" in result["error"]
