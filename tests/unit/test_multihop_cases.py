"""The harness could not see the thing the product is for.

Every other shape's gold answer is a single edge, so the whole harness measured
one-hop lookup. Multi-hop retrieval - "how did we end up here?" - is the next
version's stated differentiator, and no configuration change to it could have
been shown to help or hurt.

These pin the generator, which is pure: it takes the edge list and returns
questions no single fact answers.
"""

from __future__ import annotations

from echo_memory.eval.retrieval import (
    MULTIHOP_PER_HUB,
    SHAPE_MULTIHOP,
    _multihop_cases,
)

# (edge_id, source_id, source_name, target_id, target_name, fact)
ROWS = [
    ("e1", "1", "retry policy", "2", "payment gateway", "retries drop the key"),
    ("e2", "2", "payment gateway", "3", "settlement batch", "settlement runs nightly"),
]


def test_it_asks_about_two_entities_no_single_fact_connects():
    """retry policy and settlement batch never appear in one fact; both appear
    in facts about the payment gateway. Answering needs both edges, which is
    the definition of the question being multi-hop."""
    cases = _multihop_cases(ROWS, None)

    assert len(cases) == 1
    case = cases[0]
    assert case.shape == SHAPE_MULTIHOP
    assert "retry policy" in case.query and "settlement batch" in case.query
    assert {case.gold_edge_id, case.also_required} == {"e1", "e2"}


def test_entities_one_fact_already_joins_are_not_asked_about():
    """If a single edge connects them the question is single-hop and belongs in
    the other shapes. Including it here would flatter the multi-hop score with
    cases that never needed a traversal."""
    joined = [*ROWS, ("e3", "1", "retry policy", "3", "settlement batch", "they interact")]

    assert _multihop_cases(joined, None) == []


def test_a_self_loop_contributes_nothing():
    """A fact from a node to itself gives a query of one repeated word. The
    single-hop shapes already skip these for the same reason."""
    assert _multihop_cases([("e1", "1", "thing", "1", "thing", "a note")], None) == []


def test_one_hub_cannot_supply_the_whole_sample():
    """A 35-degree project node is incident to 595 ordered pairs. Uncapped, one
    node would dominate the sample and the score would describe that node
    rather than the store."""
    arms = [
        (f"e{i}", "0", "hub", str(i), f"leaf {i}", f"fact {i}")
        for i in range(1, 20)
    ]

    cases = _multihop_cases(arms, None)

    assert len(cases) == MULTIHOP_PER_HUB
