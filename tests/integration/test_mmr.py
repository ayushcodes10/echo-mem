"""Retrieval should not spend the whole budget on one fact said five ways.

Ranking is purely similarity to the query, so several phrasings of the same
thing all score well and all get selected. The user pays for each of them in
injected tokens and learns nothing after the first.

MMR picks the candidate maximising

    lambda * relevance(d) - (1 - lambda) * max similarity to what is chosen

with lambda 0.7, so relevance still dominates and near-duplicates are broken
up rather than variety being pursued for its own sake.

It is OFF by default, because the eval measured it making retrieval worse on
this store: R@3 0.703 to 0.653 and MRR 0.605 to 0.594, for no token saving. See
_mmr_select's docstring. These tests cover the mechanism, which is correct and
may be worth turning on once claim/detail shortens every embedded text - not a
claim that it currently helps.
"""

from __future__ import annotations

import math
import random

from echo_memory.infra.db import connect
from echo_memory.retrieval.query_memory import _mmr_select

GROUP = "user:ayush:shared"
DIM = 384


def _unit(vec):
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def _insert(conn, edge_id, vec):
    conn.execute(
        """INSERT INTO public.fact_embedding (edge_id, group_id, embedding)
           VALUES (%s::graphid, %s, %s)""",
        (edge_id, GROUP, _unit(vec)),
    )


def _cluster(rng, base, jitter=0.01):
    return [b + rng.gauss(0, jitter) for b in base]


def test_near_duplicates_do_not_take_every_slot(migrated_db):
    """Four near-identical facts ranked 1-4, one distinct fact ranked 5. Plain
    truncation returns three copies of one thing; MMR reaches for the fifth.

    top_k=3 rather than 2, because at lambda 0.7 relevance correctly still wins
    the second slot: the rank-2 duplicate scores 0.7*0.8 - 0.3*1.0 = 0.26
    against the rank-5 distinct fact's 0.7*0.2 - 0.3*0 = 0.14. By the third
    slot the duplicate has fallen to 0.12 and the distinct fact takes it. That
    is the intended trade - diversity breaks ties, it does not overrule the
    question."""
    rng = random.Random(3)
    twin = _unit([1.0] + [0.0] * (DIM - 1))
    other = _unit([0.0, 1.0] + [0.0] * (DIM - 2))

    ids = [str(1125899906842624 + i) for i in range(5)]
    with connect(migrated_db) as conn:
        for i in range(4):
            _insert(conn, ids[i], _cluster(rng, twin))
        _insert(conn, ids[4], other)

        selected = _mmr_select(conn, GROUP, ids, top_k=3)

    assert selected[0] == ids[0], "the top result must stay the top result"
    assert ids[4] in selected, (
        "the one distinct fact never got picked; the budget went on duplicates"
    )
    assert selected != ids[:3], "selection was unchanged from plain truncation"


def test_relevance_still_dominates(migrated_db):
    """Diversity must not outrank the question. With all candidates mutually
    distinct there is no redundancy to trade against, so the order stands."""
    rng = random.Random(11)
    ids = [str(1125899906842624 + i) for i in range(4)]
    with connect(migrated_db) as conn:
        for i, eid in enumerate(ids):
            vec = [0.0] * DIM
            vec[i] = 1.0
            vec[DIM - 1] = rng.gauss(0, 0.001)
            _insert(conn, eid, vec)

        assert _mmr_select(conn, GROUP, ids, top_k=3) == ids[:3]


def test_a_single_candidate_is_returned_unchanged(migrated_db):
    with connect(migrated_db) as conn:
        assert _mmr_select(conn, GROUP, ["1125899906842624"], top_k=5) == [
            "1125899906842624"
        ]


def test_missing_embeddings_fall_back_to_rank_order(migrated_db):
    """A less diverse answer beats no answer. Reordering a set where some
    candidate has no vector would be arbitrary."""
    ids = [str(1125899906842624 + i) for i in range(3)]
    with connect(migrated_db) as conn:
        _insert(conn, ids[0], [1.0] + [0.0] * (DIM - 1))
        # ids[1] and ids[2] have no embedding row at all.
        assert _mmr_select(conn, GROUP, ids, top_k=2) == ids[:2]


def test_it_never_returns_more_than_asked(migrated_db):
    rng = random.Random(5)
    ids = [str(1125899906842624 + i) for i in range(6)]
    with connect(migrated_db) as conn:
        for eid in ids:
            _insert(conn, eid, [rng.gauss(0, 1) for _ in range(DIM)])
        assert len(_mmr_select(conn, GROUP, ids, top_k=3)) == 3
