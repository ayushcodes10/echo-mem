"""The calibration arithmetic, with no database in the way.

These numbers decide whether anyone is allowed to move a threshold, so they are
pinned against cases whose answer is known by hand rather than against whatever
the implementation happened to return first.
"""

import math

from echo_memory.cli.calibrate import auc, auc_interval, operating_points


def test_perfect_separation_is_one():
    assert auc([0.9, 0.8], [0.2, 0.1]) == 1.0


def test_perfectly_wrong_separation_is_zero():
    assert auc([0.1, 0.2], [0.8, 0.9]) == 0.0


def test_identical_distributions_are_a_coin():
    assert auc([0.5, 0.5], [0.5, 0.5]) == 0.5


def test_a_tie_counts_as_half():
    """Mann-Whitney's convention, and the one that matters here: two pairs
    scoring exactly the same carry no information about which is which, and
    counting a tie as a win would flatter every threshold."""
    assert auc([0.5], [0.5]) == 0.5
    # (tie 0.5) + (win) + (win) + (win), over four comparisons.
    assert auc([0.5, 0.9], [0.5, 0.1]) == 0.875


def test_the_interval_is_reproducible_and_brackets_the_estimate():
    """A calibration nobody can recompute is one nobody should act on, so the
    bootstrap is seeded."""
    pos, neg = [0.9, 0.7, 0.6], [0.5, 0.4, 0.3, 0.2]
    first = auc_interval(pos, neg)
    assert first == auc_interval(pos, neg)

    lo, hi = first
    assert lo <= auc(pos, neg) <= hi


def test_a_handful_of_positives_gives_an_interval_that_includes_chance():
    """This store's actual shape: five confirmed duplicates against 155
    confirmed-distinct pairs, overlapping. Whatever the point estimate, the
    interval covers chance - which is the finding, and the reason the
    thresholds were not retuned on it."""
    pos = [0.477, 0.672, 0.723, 0.748, 0.927]
    # Shaped to the measured quantiles of the real 155: median 0.571, p90
    # 0.705, p95 0.745, max 0.958. A uniform spread would be a different and
    # easier problem.
    neg = (
        [0.457 + 0.0015 * i for i in range(78)]      # up to the median
        + [0.573 + 0.0038 * i for i in range(62)]    # median to p90
        + [0.706 + 0.011 * i for i in range(14)]     # the tail
        + [0.958]
    )
    assert len(neg) == 155

    lo, hi = auc_interval(pos, neg)

    assert lo < 0.5 < hi, f"interval [{lo}, {hi}] excluded chance on five positives"
    assert hi - lo > 0.3, "five positives cannot produce a tight interval"


def test_operating_points_count_reviews_not_just_rates():
    """The cost line. A threshold's precision looks fine at 50% until you see
    it came from two surfaced pairs."""
    points = {p["threshold"]: p for p in operating_points([0.9, 0.5], [0.8, 0.6, 0.4])}

    at_45 = points[0.45]
    assert at_45["recall"] == 1.0
    # Both positives and the two negatives above 0.45; the 0.4 negative is not
    # surfaced and so costs nobody a review.
    assert at_45["reviews"] == 4
    assert math.isclose(at_45["precision"], 2 / 4)

    at_85 = points[0.85]
    assert at_85["recall"] == 0.5
    assert at_85["reviews"] == 1
    assert at_85["precision"] == 1.0


def test_no_labels_is_not_a_number():
    """An AUC over an empty class is undefined, and returning 0.0 or 0.5 would
    read as a measurement."""
    assert math.isnan(auc([], [0.5]))
    assert math.isnan(auc([0.5], []))
    assert all(math.isnan(x) for x in auc_interval([0.5], [0.4, 0.3]))
