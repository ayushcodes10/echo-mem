"""Reciprocal Rank Fusion (see the design doc's Recommended Approach and
MATHS.local.md §3). k=60 and per-ranker list depth are fixed constants, not
runtime-tunable: an external review's worked example showed k has low
leverage (identical result ordering from k=10 to k=200), while list depth
moves results far more, so it's not worth exposing either as a parameter
here until there's an eval set to tune against."""

K = 60
LIST_DEPTH = 50


def reciprocal_rank_fusion(ranked_lists: list[list[str]]) -> dict[str, float]:
    """Each ranked_list is an ordered list of ids (best first), already
    score-floored and depth-capped by the caller: RRF only sees rank
    position, never the underlying score, so filtering has to happen before
    this, not after."""
    scores: dict[str, float] = {}
    for ranked_list in ranked_lists:
        for rank, item_id in enumerate(ranked_list, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (K + rank)
    return scores
