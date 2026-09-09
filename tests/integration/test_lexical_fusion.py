"""The lexical half of the hybrid ranker has to actually return something.

`websearch_to_tsquery` ANDs every term, so a fact only matched when it
contained every word of the question. Measured on six realistic questions
against twenty real facts, exactly one returned anything at all - which meant
`reciprocal_rank_fusion` was fusing a populated vector list with an empty one
and reproducing the vector ordering exactly. Hybrid retrieval was, in effect,
vector-only retrieval with extra steps.

The ANY-term function already existed for the hook path, where the same
behaviour had been found and worked around. The tool path kept the version that
does not work, which is why this went unnoticed: the code looked like a
deliberate pair.

These tests use a vector embedder that is deliberately unhelpful, so anything
retrieved has to have come through the lexical channel.
"""

from __future__ import annotations

from fake_embedder import REFERENCE, VectorEmbedder, unit_vector_at_angle

from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import write_episode
from echo_memory.retrieval.query_memory import query_memory

GROUP = "user:ayush:shared"

FACT = "The deploy branch for dugout-be is master, never main"
NOISE = "Postgres runs on port 5433 in local development"


def _embedder():
    """Every fact sits far from every query, so the vector channel cannot be
    what surfaces anything."""
    far = unit_vector_at_angle(0.02)
    return VectorEmbedder({
        FACT: far, NOISE: far,
        "deploy branch": far, "Postgres": far, "dugout-be": far,
        # The queries.
        "deploy branch policy": REFERENCE,
        "what branch is used for shipping the backend": REFERENCE,
    })


def _seed(conn):
    for i, (subject, text) in enumerate([("deploy branch", FACT), ("Postgres", NOISE)]):
        write_episode(
            conn, GROUP, f"s{i}",
            [{"name": subject, "type": "thing"}],
            [{"source": subject, "target": subject, "relation_type": "is",
              "fact": text, "confidence": "extracted"}],
            {subject: {"resolved_to": "new"}},
            _embedder(), agent_id="claude-code",
        )


def test_a_query_with_one_absent_term_still_matches(migrated_db):
    """The exact shape that returned nothing before.

    Verified against Postgres: websearch_to_tsquery('english', 'deploy branch
    policy') is 'deploy' & 'branch' & 'polici', and the fact contains no
    "policy", so the AND form matches nothing at all. Two of three terms are
    present, which is what a real question usually looks like.

    Choosing this query mattered. The first attempt used "which branch does
    dugout-be deploy from", which passed against the broken code too: the
    english config strips which/does/from as stopwords, leaving only terms the
    fact does contain."""
    with connect(migrated_db) as conn:
        _seed(conn)
        result = query_memory(conn, GROUP, "deploy branch policy", 5, _embedder())

    facts = [f["fact"] for f in result.get("facts", [])]
    assert FACT in facts, (
        "a query with one term absent from the fact returned nothing, which is "
        "what ANDing every query term does"
    )


def test_a_question_phrased_in_different_words_still_matches(migrated_db):
    """'what branch is used for shipping the backend' reduces to
    'branch' & 'use' & 'ship' & 'backend' - only "branch" is in the fact."""
    with connect(migrated_db) as conn:
        _seed(conn)
        result = query_memory(
            conn, GROUP, "what branch is used for shipping the backend", 5, _embedder()
        )

    facts = [f["fact"] for f in result.get("facts", [])]
    assert FACT in facts
    assert NOISE not in facts, "a fact sharing no terms with the query was returned"
