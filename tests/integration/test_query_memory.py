"""End-to-end tests for query_memory against a real Postgres+AGE+pgvector
database. See conftest.py for the migrated_db fixture and DB-reachability
skip. Uses the real LocalEmbedder throughout: query_memory's whole point is
ranking real semantic/lexical relevance, which a fake embedder can't
exercise meaningfully.
"""

from echo_memory.infra.db import connect
from echo_memory.ingestion.embeddings import LocalEmbedder
from echo_memory.ingestion.write_episode import write_episode
from echo_memory.retrieval.query_memory import query_memory


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


def test_semantic_query_finds_paraphrased_fact(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    _write(
        conn, embedder, "g1", "s1", "Decision", "Postgres", "uses",
        "decided to use Postgres for storage because SQLite couldn't handle concurrent writes",
    )

    result = query_memory(conn, "g1", "why did we pick Postgres over SQLite?", 10, embedder)

    assert len(result["facts"]) == 1
    assert "Postgres" in result["facts"][0]["fact"]


def test_low_similarity_match_is_not_silently_hidden(migrated_db):
    """Regression test: "what database" vs "using SQLite for now" scores
    0.281 with the real embedder, a genuine match that an earlier
    COSINE_FLOOR of 0.3 silently hid. See query_memory.py's module comment."""
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    _write(conn, embedder, "g1", "s1", "Decision", "SQLite", "uses", "using SQLite for now")

    result = query_memory(conn, "g1", "what database", 10, embedder)

    assert len(result["facts"]) == 1
    assert result["facts"][0]["fact"] == "using SQLite for now"


def test_lexical_query_finds_exact_identifier_match(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    _write(
        conn, embedder, "g1", "s1", "Decision", "AGE", "uses",
        "the PR0a spike confirmed Apache AGE traversal latency is well under budget",
    )

    result = query_memory(conn, "g1", "PR0a spike results", 10, embedder)

    assert len(result["facts"]) == 1
    assert "PR0a" in result["facts"][0]["fact"]


def test_unrelated_query_returns_nothing(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    _write(conn, embedder, "g1", "s1", "Decision", "Postgres", "uses", "decided to use Postgres")

    result = query_memory(conn, "g1", "banana bread recipe", 10, embedder)

    assert result["facts"] == []


def test_superseded_fact_excluded_from_results(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    _write(conn, embedder, "g1", "s1", "Decision", "Postgres", "uses", "using SQLite for now")
    _write(
        conn, embedder, "g1", "s2", "Decision", "Postgres", "uses",
        "switched to Postgres for durability",
    )

    result = query_memory(conn, "g1", "what database are we using", 10, embedder)

    facts = [f["fact"] for f in result["facts"]]
    assert "using SQLite for now" not in facts
    assert "switched to Postgres for durability" in facts


def test_results_scoped_to_group_id(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    _write(conn, embedder, "g1", "s1", "Decision", "Postgres", "uses", "g1 uses Postgres")
    _write(conn, embedder, "g2", "s1", "Decision", "MySQL", "uses", "g2 uses MySQL")

    result = query_memory(conn, "g1", "what database", 10, embedder)

    facts = [f["fact"] for f in result["facts"]]
    assert "g1 uses Postgres" in facts
    assert "g2 uses MySQL" not in facts


def test_causal_hint_always_null_in_v1a(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    _write(conn, embedder, "g1", "s1", "Decision", "Postgres", "uses", "uses Postgres")

    result = query_memory(conn, "g1", "Postgres", 10, embedder)

    assert result["facts"][0]["causal_hint"] is None


def test_provenance_included_in_results(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    _write(conn, embedder, "g1", "sess-abc", "Decision", "Postgres", "uses", "uses Postgres")

    result = query_memory(conn, "g1", "Postgres", 10, embedder)

    assert result["facts"][0]["provenance"]["session_id"] == "sess-abc"


def test_validation_rejects_empty_query(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    result = query_memory(conn, "g1", "", 10, embedder)
    assert "error" in result


def test_validation_rejects_non_positive_top_k(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    result = query_memory(conn, "g1", "x", 0, embedder)
    assert "error" in result


def test_validation_rejects_top_k_over_max(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    result = query_memory(conn, "g1", "x", 101, embedder)
    assert "error" in result


def test_top_k_caps_result_count(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()
    # distinct source names, not "Tool0".."Tool4": numbered variants strip to
    # the same base under the version-token guard (see resolution.py) and
    # get correctly flagged ambiguous instead of silently created, which
    # would undercount facts for a reason unrelated to what this test checks
    sources = ["Frontend", "Backend", "Scheduler", "Cache", "Worker"]
    for i, source in enumerate(sources):
        _write(
            conn, embedder, "g1", "s1", source, "Postgres", "uses",
            f"{source} uses Postgres for storage, fact {i}",
        )

    result = query_memory(conn, "g1", "Postgres", 2, embedder)

    assert len(result["facts"]) == 2
