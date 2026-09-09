"""Query shape decides the answer, so the harness has to vary it and say so.

The first version of this harness asked every question as "<source> <target>".
Once entity names were embedded into each fact that query became a literal
substring of the text it was scoring, and it inverted a real conclusion: under
it, dropping the lexical channel measures +0.11 MRR and looks like a
significant win, while on prose queries the same change is -0.08, significantly
worse. One default shape produced two opposite answers about the same code.

And MRR is a mean, so it has a standard error. At n=219 that is about 0.023,
which makes any difference under roughly 0.047 indistinguishable from zero.
Differences of 0.001 to 0.01 were written down as findings before anyone
computed it.
"""

from __future__ import annotations

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.eval.retrieval import (
    SHAPE_ENTITY_PAIR,
    SHAPE_ENTITY_SINGLE,
    SHAPE_PROSE,
    Result,
    build_cases,
    compare,
)
from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"
SOURCE = "updateSquad"
TARGET = "Entity Sports API"
FACT = f"{SOURCE} calls the {TARGET} every ten minutes and logs a sync failure"


def _embedder():
    return VectorEmbedder({SOURCE: REFERENCE, TARGET: REFERENCE, FACT: REFERENCE})


def _seed(conn):
    write_episode(
        conn, GROUP, "s1",
        [{"name": SOURCE, "type": "job"}, {"name": TARGET, "type": "service"}],
        [{"source": SOURCE, "target": TARGET, "relation_type": "calls",
          "fact": FACT, "confidence": "extracted"}],
        {SOURCE: {"resolved_to": "new"}, TARGET: {"resolved_to": "new"}},
        _embedder(), agent_id="claude-code",
    )


def test_each_shape_asks_a_different_question(migrated_db):
    with connect(migrated_db) as conn:
        _seed(conn)
        pair = build_cases(conn, GROUP, shape=SHAPE_ENTITY_PAIR)[0]
        single = build_cases(conn, GROUP, shape=SHAPE_ENTITY_SINGLE)[0]
        prose = build_cases(conn, GROUP, shape=SHAPE_PROSE)[0]

    assert pair.query == f"{SOURCE} {TARGET}"
    assert single.query == SOURCE
    assert prose.query != pair.query


def test_the_prose_shape_removes_both_entity_names(migrated_db):
    """The whole point of it. Entity names are embedded into every fact, so a
    query containing them overlaps the text being scored; with them gone
    nothing can leak."""
    with connect(migrated_db) as conn:
        _seed(conn)
        prose = build_cases(conn, GROUP, shape=SHAPE_PROSE)[0]

    assert SOURCE.lower() not in prose.query.lower()
    assert TARGET.lower() not in prose.query.lower()
    assert "ten minutes" in prose.query


def test_an_unknown_shape_is_refused(migrated_db):
    with connect(migrated_db) as conn, pytest.raises(ValueError, match="shape must be"):
        build_cases(conn, GROUP, shape="whatever-i-felt-like")


def _result(name, ranks):
    r = Result(name=name)
    r.cases = len(ranks)
    r.reciprocal_ranks = list(ranks)
    return r


def test_a_real_difference_is_called_significant():
    base = _result("base", [0.0] * 100)
    better = _result("better", [1.0] * 100)
    verdict = compare(base, better)

    assert verdict["delta"] == pytest.approx(1.0)
    assert verdict["significant"]


def test_a_tiny_difference_is_called_noise():
    """The failure this exists to prevent: 0.001 reported as a finding."""
    base = _result("base", [1.0, 0.0] * 60)
    almost = _result("almost", [1.0, 0.0] * 59 + [1.0, 0.01])
    verdict = compare(base, almost)

    assert abs(verdict["delta"]) < 0.01
    assert not verdict["significant"], "a 0.0001 difference was called significant"


def test_the_comparison_is_paired():
    """Two configurations agreeing on almost every case have a much tighter
    interval than their separate standard errors suggest. Unpaired, this
    difference would vanish into the spread of each mean."""
    ranks = [1.0 if i % 3 else 0.0 for i in range(150)]
    base = _result("base", ranks)
    # Identical everywhere except a consistent small gain on the misses.
    variant = _result("variant", [r if r else 0.5 for r in ranks])
    verdict = compare(base, variant)

    assert verdict["delta"] > 0
    assert verdict["significant"], "a consistent per-case gain was lost as noise"


def test_comparing_different_case_sets_is_refused():
    """Pairing is meaningless if the rows do not correspond."""
    with pytest.raises(ValueError, match="same cases"):
        compare(_result("a", [1.0, 0.0]), _result("b", [1.0]))


def test_the_standard_error_is_reported():
    r = _result("r", [1.0, 0.0] * 50)
    assert r.mrr_stderr > 0
    assert r.mrr_stderr < 1
