"""A curve is a stronger claim than a point, and an easier one to fake.

`--context --sweep` exists to answer "96.7% less than what, and does it hold as
the store grows?". The specific dishonesty it must not permit is the one the
single number already had to be pinned against: a saving that rises because
retrieval quietly returned less, or nothing. So the hit rate is pinned into
every row rather than only the summary, and the renderer is pinned to refuse to
draw a curve through one point.
"""

from __future__ import annotations

from echo_memory.eval.sweep import MIN_FACTS, Point, render, sizes_for


def _point(facts: int, inject: int, recall: int, hit: float = 0.87) -> Point:
    return Point(facts=facts, inject_tokens=inject, recall_tokens=recall,
                 hit_at_10=hit, cases=facts)


# ------------------------------------------------------------------ sizes


def test_it_halves_down_from_the_whole_store():
    """Absolute sizes would either stop short of a large store or run past a
    small one. The range that matters is this store's own."""
    assert sizes_for(1_600, steps=5) == [100, 200, 400, 800, 1_600]


def test_it_stops_before_a_scope_too_small_to_measure():
    sizes = sizes_for(100, steps=5)

    assert all(s >= MIN_FACTS for s in sizes)
    assert sizes == [25, 50, 100]


def test_a_store_smaller_than_the_floor_sweeps_nothing():
    assert sizes_for(MIN_FACTS - 1) == []


# ------------------------------------------------------------------ render


def test_every_row_carries_its_own_hit_rate():
    """Not just the summary. A reader quoting one row has to carry the caveat
    with it, because the saving in that row is worthless without it."""
    text = render([_point(100, 12_000, 1_200, hit=0.84),
                   _point(800, 96_000, 1_250, hit=0.88)])

    assert "0.840" in text
    assert "0.880" in text


def test_the_saving_is_computed_against_that_size_not_the_largest():
    """The whole point of the sweep. 1,200 of 12,000 is 90%, and it must not
    borrow the 98.7% that the 800-fact row earns."""
    text = render([_point(100, 12_000, 1_200), _point(800, 96_000, 1_250)])

    assert "90.0%" in text
    assert "98.7%" in text


def test_it_says_how_far_the_recall_cost_drifted():
    """The claim is that a bounded number grows against an unbounded one. If
    the bounded one moved, the summary has to say so rather than assert the
    shape it hoped for."""
    text = render([_point(100, 12_000, 1_000), _point(800, 96_000, 1_300)])

    assert "+30%" in text
    assert "8x" in text


def test_one_point_is_refused_rather_than_drawn_as_a_curve():
    text = render([_point(100, 12_000, 1_200)])

    assert "not enough corpus" in text
    assert "%" not in text.split("already prints")[0].replace("--context", "")


def test_a_configuration_that_returned_nothing_is_visibly_worthless():
    """Same guard as the single number: 100% saving, 0.000 hit rate, printed
    side by side so the row reads as broken rather than excellent."""
    text = render([_point(100, 12_000, 0, hit=0.0),
                   _point(800, 96_000, 0, hit=0.0)])

    assert "100.0%" in text
    assert "0.000" in text
