"""A saving is only a saving if the answer survived the cut.

`--context` exists to support a public claim - that recall injects far less
context than putting the whole scope in the prompt - and a number on a landing
page needs to be hard to state dishonestly. The failure mode is specific and
easy: a configuration that returns nothing scores a perfect saving. So the
renderer is pinned to print the hit rate beside every saving it reports, and to
report the honest 100% when that is what happened rather than hiding it.

The percentage is also a property of the store rather than of the software, and
rises as the store grows. These pin that the corpus size it was computed
against is printed, so nobody can quote the percentage without the denominator.
"""

from __future__ import annotations

from echo_memory.eval.retrieval import (
    SHAPE_ENTITY_SINGLE,
    SHAPE_PROSE,
    Result,
    render_context_saving,
)


def _result(shape: str, cases: int, chars_each: int, hits_at_10: int) -> Result:
    r = Result(name="shipping", shape=shape)
    r.cases = cases
    r.returned_chars = [chars_each] * cases
    r.hits_at[10] = hits_at_10
    r.reciprocal_ranks = [1.0] * hits_at_10 + [0.0] * (cases - hits_at_10)
    return r


def test_it_reports_the_saving_against_the_whole_scope():
    """400 tokens returned against a 40,000-token scope is 99% less."""
    r = _result(SHAPE_ENTITY_SINGLE, cases=10, chars_each=1_600, hits_at_10=9)
    text = render_context_saving([r], facts=300, whole=40_000)

    assert "99.0%" in text
    assert "400" in text


def test_the_hit_rate_is_printed_beside_the_saving():
    """The whole point. Without it the number says only that less came back."""
    r = _result(SHAPE_ENTITY_SINGLE, cases=10, chars_each=1_600, hits_at_10=9)
    text = render_context_saving([r], facts=300, whole=40_000)

    assert "hit@10" in text
    assert "0.900" in text


def test_returning_nothing_scores_a_perfect_saving_and_a_zero_hit_rate():
    """The dishonest reading this guards against: a configuration that answers
    no question at all is a 100% saving. It must be visibly worthless next to
    it, not quietly excellent."""
    r = _result(SHAPE_ENTITY_SINGLE, cases=10, chars_each=0, hits_at_10=0)
    text = render_context_saving([r], facts=300, whole=40_000)

    assert "100.0%" in text
    assert "0.000" in text


def test_the_denominator_is_printed():
    """A saving quoted without the corpus it was measured against is not a
    claim anyone can check, and it moves as the store grows."""
    text = render_context_saving(
        [_result(SHAPE_ENTITY_SINGLE, 10, 1_600, 9)], facts=325, whole=41_838
    )

    assert "325" in text
    assert "41,838" in text


def test_shapes_are_weighted_by_case_count():
    """A shape with twice the cases carries twice the weight; a flat mean of
    the per-shape percentages would let a small shape move the headline."""
    many = _result(SHAPE_ENTITY_SINGLE, cases=90, chars_each=400, hits_at_10=90)
    few = _result(SHAPE_PROSE, cases=10, chars_each=4_000, hits_at_10=0)

    text = render_context_saving([many, few], facts=300, whole=40_000)

    # 90 cases at 100 tokens and 10 at 1,000 average 190, not 550.
    assert "190" in text
    assert "weighted" in text
    # and the weighted hit rate is 0.900, not the flat-mean 0.500
    assert "0.900" in text


def test_no_cases_is_not_a_perfect_score():
    assert render_context_saving([], facts=0, whole=0) == "no cases"
    assert render_context_saving(
        [_result(SHAPE_ENTITY_SINGLE, 0, 0, 0)], facts=0, whole=0
    ) == "no cases"
