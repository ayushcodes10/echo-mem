"""The harness that decides whether a retrieval change helped.

It has to be trustworthy before its numbers are, so these check the parts that
would silently produce a flattering result: that cases are built only from
facts that can actually be scored, that a hit is a hit at the right rank, and
that a miss is scored as a miss rather than skipped.
"""

from __future__ import annotations

from fake_embedder import REFERENCE, VectorEmbedder, unit_vector_at_angle

from echo_memory.eval.retrieval import build_cases, render, run
from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"

FACT = "The deploy branch for dugout-be is master, never main"
OTHER = "Postgres listens on port 5433 in local development"


def _embedder():
    near = unit_vector_at_angle(0.9)
    far = unit_vector_at_angle(0.05)
    return VectorEmbedder({
        FACT: REFERENCE, OTHER: far,
        "deploy branch": near, "dugout-be": near,
        "Postgres": far, "port 5433": far,
        "deploy branch dugout-be": REFERENCE,
        "Postgres port 5433": far,
        "self referential": far,
        "a fact about one thing": far,
    })


def _write(conn, source, target, text):
    write_episode(
        conn, GROUP, "s1",
        [{"name": source, "type": "thing"}] + ([] if source == target else
                                               [{"name": target, "type": "thing"}]),
        [{"source": source, "target": target, "relation_type": "is",
          "fact": text, "confidence": "extracted"}],
        {source: {"resolved_to": "new"}, target: {"resolved_to": "new"}},
        _embedder(), agent_id="claude-code",
    )


def test_a_case_is_built_per_fact_joining_two_entities(migrated_db):
    with connect(migrated_db) as conn:
        _write(conn, "deploy branch", "dugout-be", FACT)
        cases = build_cases(conn, GROUP)

    assert len(cases) == 1
    assert cases[0].query == "deploy branch dugout-be"
    assert cases[0].gold_fact == FACT


def test_self_loops_are_excluded(migrated_db):
    """A fact from a node to itself gives a query of one repeated word, which
    measures nothing about ranking. They are over-represented here because an
    agent reaches for a self-edge when a fact has no natural second entity, so
    leaving them in would quietly inflate every score."""
    with connect(migrated_db) as conn:
        _write(conn, "self referential", "self referential", "a fact about one thing")
        assert build_cases(conn, GROUP) == []


def test_a_retrieved_gold_fact_counts_as_a_hit(migrated_db):
    with connect(migrated_db) as conn:
        _write(conn, "deploy branch", "dugout-be", FACT)
        cases = build_cases(conn, GROUP)
        result = run(conn, GROUP, _embedder(), cases, "test")

    assert result.cases == 1
    assert result.recall(1) == 1.0
    assert result.mrr == 1.0
    assert result.mean_tokens > 0


def test_a_missing_gold_fact_is_scored_as_a_miss(migrated_db):
    """The failure that would make every configuration look perfect: scoring a
    case only when something came back."""
    with connect(migrated_db) as conn:
        _write(conn, "deploy branch", "dugout-be", FACT)
        cases = build_cases(conn, GROUP)
        # Ask for something with no lexical or vector overlap at all.
        missed = [type(cases[0])(query="Postgres port 5433",
                                 gold_edge_id="999999999999",
                                 gold_fact="nothing")]
        result = run(conn, GROUP, _embedder(), missed, "test")

    assert result.cases == 1
    assert result.recall(1) == 0.0
    assert result.mrr == 0.0


def test_an_empty_answer_is_counted(migrated_db):
    """Abstention is a metric, not an absence of one. A configuration that
    declines half the questions has to be visible as such.

    Both channels have to be silenced to produce one. A high floor alone does
    not abstain, because it gates the vector candidates only and the lexical
    channel still matches on the entity names - which is worth knowing before
    anyone tunes the floor expecting it to control abstention."""
    with connect(migrated_db) as conn:
        _write(conn, "deploy branch", "dugout-be", FACT)
        cases = build_cases(conn, GROUP)
        # Above 1.0, which cosine cannot exceed, so nothing clears it. 0.99
        # does not work here: this embedder maps the query and the fact to the
        # same vector, so they score exactly 1.0.
        result = run(
            conn, GROUP, _embedder(), cases, "test", floor=1.01, vector_only=True
        )

    assert result.cases == 1
    assert result.abstention_rate == 1.0
    assert result.mean_tokens == 0


def test_render_survives_no_configurations():
    assert "no configurations" in render([])
