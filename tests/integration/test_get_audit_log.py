"""End-to-end tests for get_audit_log against a real Postgres+AGE+pgvector
database. See conftest.py for the migrated_db fixture and DB-reachability
skip."""

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.audit.get_audit_log import get_audit_log
from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import write_episode


def _write(conn, embedder, group_id, session_id, source, target, relation_type, fact):
    return write_episode(
        conn,
        group_id,
        session_id,
        [{"name": source, "type": "tool"}, {"name": target, "type": "tool"}],
        [
            {
                "source": source,
                "target": target,
                "relation_type": relation_type,
                "fact": fact,
                "confidence": "extracted",
            }
        ],
        {},
        embedder,
    )


def test_created_entry_recorded(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder({"Decision": REFERENCE, "Postgres": REFERENCE, "uses Postgres": REFERENCE})
    _write(conn, embedder, "g1", "sess-1", "Decision", "Postgres", "uses", "uses Postgres")

    result = get_audit_log(conn, "g1")

    created = [e for e in result["entries"] if e["mutation_type"] == "created"]
    assert len(created) == 1
    assert created[0]["session_id"] == "sess-1"
    assert created[0]["affected_edge_ids"] != []
    assert created[0]["affected_node_id"] is None


def test_fact_superseded_records_before_and_after(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder(
        {
            "Decision": REFERENCE,
            "Postgres": REFERENCE,
            "using SQLite for now": REFERENCE,
            "switched to Postgres for durability": REFERENCE,
        }
    )
    _write(conn, embedder, "g1", "s1", "Decision", "Postgres", "uses", "using SQLite for now")
    _write(
        conn, embedder, "g1", "s2", "Decision", "Postgres", "uses",
        "switched to Postgres for durability",
    )

    result = get_audit_log(conn, "g1")

    superseded = [e for e in result["entries"] if e["mutation_type"] == "fact_superseded"]
    assert len(superseded) == 1
    assert superseded[0]["before_fact"] == "using SQLite for now"
    assert superseded[0]["after_fact"] == "switched to Postgres for durability"
    assert len(superseded[0]["affected_edge_ids"]) == 2


def test_entity_resolved_records_node_id_and_detail(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder({"Postgres": REFERENCE, "postgres": REFERENCE, "uses postgres": REFERENCE})
    _write(conn, embedder, "g1", "s1", "Postgres", "Postgres", "self", "uses postgres")
    # second call resolves "postgres" via exact (case-insensitive) match
    write_episode(
        conn, "g1", "s2",
        [{"name": "postgres", "type": "tool"}],
        [],
        {},
        embedder,
    )

    result = get_audit_log(conn, "g1")

    resolved = [e for e in result["entries"] if e["mutation_type"] == "entity_resolved"]
    assert any(e["resolution_detail"] == "exact match" for e in resolved)
    assert all(e["affected_node_id"] is not None for e in resolved)


def test_entries_ordered_chronologically(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder({"A": REFERENCE, "B": REFERENCE, "fact one": REFERENCE, "fact two": REFERENCE})
    _write(conn, embedder, "g1", "s1", "A", "B", "rel1", "fact one")
    _write(conn, embedder, "g1", "s2", "A", "B", "rel2", "fact two")

    result = get_audit_log(conn, "g1")

    timestamps = [e["timestamp"] for e in result["entries"]]
    assert timestamps == sorted(timestamps)


def test_since_filters_out_earlier_entries(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder({"A": REFERENCE, "B": REFERENCE, "fact one": REFERENCE, "fact two": REFERENCE})
    _write(conn, embedder, "g1", "s1", "A", "B", "rel1", "fact one")
    midpoint = get_audit_log(conn, "g1")["entries"][-1]["timestamp"]
    _write(conn, embedder, "g1", "s2", "A", "B", "rel2", "fact two")

    result = get_audit_log(conn, "g1", since=midpoint)

    assert all(e["timestamp"] >= midpoint for e in result["entries"])
    assert any(e["session_id"] == "s2" for e in result["entries"])


def test_scoped_to_group_id(migrated_db):
    conn = connect(migrated_db)
    embedder = VectorEmbedder({"A": REFERENCE, "B": REFERENCE, "g1 fact": REFERENCE, "g2 fact": REFERENCE})
    _write(conn, embedder, "g1", "s1", "A", "B", "rel", "g1 fact")
    _write(conn, embedder, "g2", "s1", "A", "B", "rel", "g2 fact")

    result = get_audit_log(conn, "g1")

    assert all(e["session_id"] != "g2-only" for e in result["entries"])
    summaries = [e["summary"] for e in result["entries"]]
    assert any("g1 fact" in s for s in summaries)
    assert not any("g2 fact" in s for s in summaries)


def test_empty_group_returns_empty_list_not_error(migrated_db):
    conn = connect(migrated_db)
    result = get_audit_log(conn, "nonexistent-group")
    assert result == {"entries": []}


def test_validation_rejects_malformed_since(migrated_db):
    conn = connect(migrated_db)
    result = get_audit_log(conn, "g1", since="not-a-timestamp")
    assert "error" in result
