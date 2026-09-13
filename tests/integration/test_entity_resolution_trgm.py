"""Entity resolution needs a lexical signal for technical identifiers."""

from fake_embedder import REFERENCE, VectorEmbedder, unit_vector_at_angle

from echo_memory.infra.db import connect
from echo_memory.ingestion.resolution import resolve_entities
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:echo-mem:trigram"
CANONICAL = "AWS Organizations SCP p-zlhv81t8"
MENTION = "AWS Org SCP p-zlhv81t8"


def _embedder():
    # Deliberately make the embedding channel miss this abbreviation pair.
    return VectorEmbedder({
        CANONICAL: REFERENCE,
        MENTION: unit_vector_at_angle(0.02),
    })


def test_trigram_candidates_surface_identifier_abbreviations(migrated_db):
    """A lexical-only match must be offered for agent confirmation.

    The two names carry the same identifier but differ in expansion.  Their
    controlled embeddings are intentionally dissimilar, so this fails when
    resolution only consults node_embedding.
    """
    embedder = _embedder()
    with connect(migrated_db) as conn:
        write_episode(
            conn,
            GROUP,
            "seed-trigram",
            [{"name": CANONICAL, "type": "thing"}],
            [],
            {CANONICAL: {"resolved_to": "new"}},
            embedder,
            agent_id="test-agent",
        )
        outcome = resolve_entities(
            conn,
            GROUP,
            [{"name": MENTION, "type": "thing"}],
            {},
            embedder,
        )

    assert len(outcome.ambiguous) == 1
    assert outcome.ambiguous[0].mention == MENTION
    assert outcome.ambiguous[0].candidates[0].name == CANONICAL
    assert outcome.ambiguous[0].candidates[0].similarity >= 0.45
