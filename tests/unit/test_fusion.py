from echo_memory.retrieval.fusion import K, reciprocal_rank_fusion


def test_top_of_both_lists_wins():
    vector = ["a", "b", "c"]
    lexical = ["a", "c", "b"]
    scores = reciprocal_rank_fusion([vector, lexical])
    assert scores["a"] > scores["b"]
    assert scores["a"] > scores["c"]


def test_missing_from_one_list_still_scores():
    vector = ["a", "b"]
    lexical = ["c"]
    scores = reciprocal_rank_fusion([vector, lexical])
    assert set(scores) == {"a", "b", "c"}
    assert scores["a"] == 1 / (K + 1)
    assert scores["c"] == 1 / (K + 1)


def test_appearing_in_both_lists_beats_appearing_in_one():
    # rank 3 in both lists vs rank 1 in only one list: RRF rewards showing up
    # in every ranker over winning a single race, even at a mediocre rank
    vector = ["x", "y", "z"]
    lexical = ["p", "q", "z"]
    scores = reciprocal_rank_fusion([vector, lexical])
    assert scores["z"] == 1 / (K + 3) + 1 / (K + 3)
    assert scores["x"] == 1 / (K + 1)
    assert scores["z"] > scores["x"]


def test_empty_lists_produce_empty_scores():
    assert reciprocal_rank_fusion([[], []]) == {}


def test_single_list_preserves_relative_order():
    scores = reciprocal_rank_fusion([["a", "b", "c"]])
    assert scores["a"] > scores["b"] > scores["c"]
