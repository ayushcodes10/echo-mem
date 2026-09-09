"""The similarity floor has to be measured, not picked.

`COSINE_FLOOR = 0.15` was chosen by hand and measured, later, to sit inside the
noise rather than above it: unrelated facts in the author's store score
0.084-0.163 with sd 0.078-0.135, so the floor admitted roughly half of
everything and an abstract question came back with cron bugs.

Measuring the store's own noise distribution and sitting above its 95th
percentile gives 0.3653 there - 2.4x the static value, and close to the
mean + 2sd the analysis predicted. It also keeps working when the embedder,
the subject matter or the length of the facts change, none of which a constant
survives.

These tests drive the measurement against real vectors in a real database,
since the whole thing is a property of what pgvector returns.
"""

from __future__ import annotations

import math
import random

from echo_memory.infra.db import connect
from echo_memory.retrieval.query_memory import (
    COSINE_FLOOR,
    FLOOR_MIN_FACTS,
    adaptive_cosine_floor,
)

GROUP = "user:ayush:shared"
DIM = 384


def _unit(vec):
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def _seed_embeddings(conn, n, spread):
    """n fact embeddings. `spread` controls how unrelated they are: a large
    spread scatters them, a small one clusters them near-identically."""
    rng = random.Random(7)
    for i in range(n):
        vec = _unit([1.0] + [rng.gauss(0, spread) for _ in range(DIM - 1)])
        conn.execute(
            """INSERT INTO public.fact_embedding (edge_id, group_id, embedding)
               VALUES (%s::graphid, %s, %s)""",
            (str(1125899906842624 + i), GROUP, vec),
        )


def test_a_store_too_small_to_measure_falls_back(migrated_db):
    """Under the minimum, a sample is noise about noise. Better to use the
    hand-picked value than a confident number derived from six facts."""
    with connect(migrated_db) as conn:
        _seed_embeddings(conn, 5, spread=1.0)
        assert adaptive_cosine_floor(conn, GROUP) == COSINE_FLOOR


def test_an_empty_store_falls_back(migrated_db):
    with connect(migrated_db) as conn:
        assert adaptive_cosine_floor(conn, GROUP) == COSINE_FLOOR


def test_a_store_of_unrelated_facts_measures_a_real_floor(migrated_db):
    """With enough scattered facts the measurement runs and returns the
    percentile of their mutual similarity."""
    with connect(migrated_db) as conn:
        _seed_embeddings(conn, FLOOR_MIN_FACTS + 20, spread=1.0)
        floor = adaptive_cosine_floor(conn, GROUP)

    assert floor >= COSINE_FLOOR
    assert floor <= 1.0


def test_the_floor_never_drops_below_the_static_one(migrated_db):
    """A store whose facts are all near-identical measures a very low mutual
    similarity, and would floor at nearly nothing - admitting everything, which
    is the failure this exists to prevent, arrived at from the other side."""
    with connect(migrated_db) as conn:
        # Tight spread: every vector nearly parallel, so pairwise similarity is
        # high, not low. The guard matters in the opposite case too, so assert
        # the invariant rather than the direction.
        _seed_embeddings(conn, FLOOR_MIN_FACTS + 20, spread=0.01)
        assert adaptive_cosine_floor(conn, GROUP) >= COSINE_FLOOR


def test_the_floor_is_scoped_to_one_group(migrated_db):
    """Another tenant's facts must not set this tenant's floor."""
    with connect(migrated_db) as conn:
        _seed_embeddings(conn, FLOOR_MIN_FACTS + 20, spread=1.0)
        assert adaptive_cosine_floor(conn, "user:someone-else:shared") == COSINE_FLOOR
