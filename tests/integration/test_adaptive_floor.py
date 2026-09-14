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
    reset_floor_cache,
)

GROUP = "user:ayush:shared"
DIM = 384


def _unit(vec):
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


# Every call takes a fresh block of ids. Two reasons, both bugs that were live:
# the floor is cached per (fact count, highest id), and three tests here seed
# the same count into the same scope with different spreads - identical keys,
# so the second would have been served the first's answer. And an interrupted
# test run leaves rows behind that its teardown never dropped, which made the
# next run's first insert collide on the primary key.
_next_base = [1125899906842624]


def _seed_embeddings(conn, n, spread, *, group=GROUP):
    """n fact embeddings. `spread` controls how unrelated they are: a large
    spread scatters them, a small one clusters them near-identically."""
    conn.execute("DELETE FROM public.fact_embedding WHERE group_id = %s", (group,))
    base = _next_base[0]
    _next_base[0] += max(n, 1) + 1
    rng = random.Random(7)
    for i in range(n):
        vec = _unit([1.0] + [rng.gauss(0, spread) for _ in range(DIM - 1)])
        conn.execute(
            """INSERT INTO public.fact_embedding (edge_id, group_id, embedding)
               VALUES (%s::graphid, %s, %s)""",
            (str(base + i), group, vec),
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


def test_the_measured_floor_is_the_same_every_time(migrated_db):
    """It used to be ORDER BY random(), redrawn per call, so the floor moved
    between 0.408 and 0.431 on the real store and identical queries returned
    different answers. Three of ten evaluation questions changed their result
    list across three identical runs because of it."""
    with connect(migrated_db) as conn:
        _seed_embeddings(conn, FLOOR_MIN_FACTS + 20, spread=1.0)
        reset_floor_cache()
        measured = {adaptive_cosine_floor(conn, GROUP) for _ in range(5)}
        reset_floor_cache()
        measured |= {adaptive_cosine_floor(conn, GROUP) for _ in range(5)}

    assert len(measured) == 1, f"the floor moved between calls: {sorted(measured)}"


def test_a_changed_store_is_measured_again(migrated_db):
    """The cache is keyed on the fact count and the highest id because those
    are what the answer depends on. A scope that has gained facts has to be
    re-measured, or the floor describes a store that no longer exists."""
    with connect(migrated_db) as conn:
        _seed_embeddings(conn, FLOOR_MIN_FACTS + 20, spread=1.0)
        reset_floor_cache()
        scattered = adaptive_cosine_floor(conn, GROUP)
        # Same count, same scope, different content and a fresh id block.
        _seed_embeddings(conn, FLOOR_MIN_FACTS + 20, spread=0.01)
        clustered = adaptive_cosine_floor(conn, GROUP)

    assert clustered != scattered, "a rewritten store returned the cached floor"


def test_the_cache_does_not_leak_between_scopes(migrated_db):
    """One tenant's measured floor must never be served to another.

    Seeded tightly on purpose: scattered facts measure a percentile below the
    static floor and max() returns COSINE_FLOOR, which is the same value an
    empty scope returns - so a leak would be invisible. Clustered facts measure
    well above it, and the two answers can be told apart."""
    with connect(migrated_db) as conn:
        _seed_embeddings(conn, FLOOR_MIN_FACTS + 20, spread=0.01)
        reset_floor_cache()
        mine = adaptive_cosine_floor(conn, GROUP)
        theirs = adaptive_cosine_floor(conn, "user:someone-else:shared")

    assert mine > COSINE_FLOOR
    assert theirs == COSINE_FLOOR
