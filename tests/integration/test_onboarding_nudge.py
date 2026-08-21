"""End-to-end tests for the first-use onboarding nudge (CEO plan scope
decision #6): a live query_memory digest sample attached to write_episode's
response on exactly the 3rd call for a group_id. See conftest.py for the
migrated_db fixture and DB-reachability skip."""

from echo_memory.infra.db import connect
from echo_memory.ingestion.embeddings import LocalEmbedder
from echo_memory.ingestion.write_episode import write_episode


def _write(conn, embedder, group_id, session_id, relation_type, fact):
    return write_episode(
        conn,
        group_id,
        session_id,
        [{"name": "A", "type": "tool"}, {"name": "B", "type": "tool"}],
        [
            {
                "source": "A",
                "target": "B",
                "relation_type": relation_type,
                "fact": fact,
                "confidence": "extracted",
            }
        ],
        {},
        embedder,
    )


def test_nudge_fires_on_exactly_the_third_call(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()

    r1 = _write(conn, embedder, "g1", "s1", "r1", "fact one")
    r2 = _write(conn, embedder, "g1", "s2", "r2", "fact two")
    r3 = _write(conn, embedder, "g1", "s3", "r3", "fact three")
    r4 = _write(conn, embedder, "g1", "s4", "r4", "fact four")

    assert "onboarding_sample" not in r1
    assert "onboarding_sample" not in r2
    assert "onboarding_sample" in r3
    assert "onboarding_sample" not in r4


def test_nudge_sample_is_a_live_digest_of_the_groups_own_data(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()

    _write(conn, embedder, "g1", "s1", "r1", "fact one")
    _write(conn, embedder, "g1", "s2", "r2", "fact two")
    r3 = _write(conn, embedder, "g1", "s3", "r3", "fact three")

    sample_facts = [f["fact"] for f in r3["onboarding_sample"]]
    assert "fact three" in sample_facts or "fact two" in sample_facts or "fact one" in sample_facts
    assert len(sample_facts) >= 1


def test_nudge_counter_is_per_group_id(migrated_db):
    conn = connect(migrated_db)
    embedder = LocalEmbedder()

    _write(conn, embedder, "g1", "s1", "r1", "g1 fact one")
    _write(conn, embedder, "g1", "s2", "r2", "g1 fact two")
    _write(conn, embedder, "g1", "s3", "r3", "g1 fact three")

    # a different group_id starts its own counter from zero
    r_g2 = _write(conn, embedder, "g2", "s1", "r1", "g2 fact one")

    assert "onboarding_sample" not in r_g2


def test_nudge_counts_calls_even_when_entities_are_ambiguous(migrated_db):
    """The counter tracks write_episode *calls*, not facts successfully
    created: a call that only resolves entities (e.g. all facts deferred as
    ambiguous) still counts toward the 3rd-call trigger."""
    conn = connect(migrated_db)
    embedder = LocalEmbedder()

    r1 = write_episode(conn, "g1", "s1", [{"name": "X", "type": "tool"}], [], {}, embedder)
    r2 = write_episode(conn, "g1", "s2", [{"name": "Y", "type": "tool"}], [], {}, embedder)
    r3 = write_episode(conn, "g1", "s3", [{"name": "Z", "type": "tool"}], [], {}, embedder)

    assert "onboarding_sample" not in r1
    assert "onboarding_sample" not in r2
    assert "onboarding_sample" in r3
