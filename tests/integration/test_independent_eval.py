"""The evaluation whose questions predate its answers, and what enforces that.

Three review rounds established that the answer-derived harness cannot settle
which configuration should ship: a biased task can change which one wins, not
only the level of both. This is the instrument that can, and its whole value is
in properties that are easy to lose in a refactor - a question retrieved for
before it was stored, a label that carries a configuration's identity, a recall
figure quietly computed over a pool while claiming to be over the store.

Each of those is pinned here.
"""

from __future__ import annotations

import pytest
from fake_embedder import REFERENCE, VectorEmbedder, unit_vector_at_angle

from echo_memory.eval import independent
from echo_memory.infra.db import connect

GROUP = "user:ayush:shared"
FACT_A = "the deploy branch is main, never master"
FACT_B = "the cache is invalidated on write"
FAR = unit_vector_at_angle(0.05)


def _embedder():
    return VectorEmbedder({
        "Acme": REFERENCE, "release branch": REFERENCE, FACT_A: REFERENCE,
        "cache": FAR, "write path": FAR, FACT_B: FAR,
        "which branch does it deploy from": REFERENCE,
    })


@pytest.fixture
def conn(migrated_db):
    from echo_memory.ingestion.write_episode import write_episode

    with connect(migrated_db) as c:
        embedder = _embedder()
        write_episode(
            c, GROUP, "s1",
            [{"name": "Acme", "type": "company"},
             {"name": "release branch", "type": "policy"}],
            [{"source": "Acme", "target": "release branch", "relation_type": "deploys_from",
              "fact": FACT_A, "confidence": "extracted"}],
            {"Acme": {"resolved_to": "new"}, "release branch": {"resolved_to": "new"}},
            embedder, project="echo-mem", agent_id="claude-code",
        )
        write_episode(
            c, GROUP, "s1",
            [{"name": "cache", "type": "component"},
             {"name": "write path", "type": "component"}],
            [{"source": "cache", "target": "write path", "relation_type": "affected_by",
              "fact": FACT_B, "confidence": "extracted"}],
            {"cache": {"resolved_to": "new"}, "write path": {"resolved_to": "new"}},
            embedder, project="echo-mem", agent_id="claude-code",
        )
        yield c


def test_recording_a_question_retrieves_nothing(conn):
    """The ordering is the independence. A question stored before anything was
    retrieved for it cannot have been fitted to a result that did not exist -
    and `opened_at` is what lets a later reader tell which came first."""
    result = independent.add_question(conn, GROUP, "which branch does it deploy from")

    assert result["created"] is True
    stored = independent.questions(conn, GROUP)[0]
    assert stored["opened_at"] is None
    assert conn.execute(
        "SELECT count(*) FROM public.eval_run WHERE question_id = %s", (result["id"],)
    ).fetchone()[0] == 0


def test_the_same_question_twice_is_one_question(conn):
    """Two copies would be judged twice and counted twice."""
    first = independent.add_question(conn, GROUP, "which branch does it deploy from")
    again = independent.add_question(conn, GROUP, "  which branch does it   deploy from ")

    assert again["created"] is False
    assert again["id"] == first["id"]


def test_opening_records_every_configuration_and_stamps_the_question(conn):
    q = independent.add_question(conn, GROUP, "which branch does it deploy from")
    question = independent.questions(conn, GROUP)[0]

    independent.run_configurations(
        conn, GROUP, question, _embedder(),
        {"shipping": {}, "vector only": {"vector_only": True}},
    )

    assert independent.questions(conn, GROUP)[0]["opened_at"] is not None
    assert conn.execute(
        "SELECT count(*) FROM public.eval_run WHERE question_id = %s", (q["id"],)
    ).fetchone()[0] == 2


def test_the_pool_is_a_deduplicated_union(conn):
    """A fact several configurations found is one thing to judge. Judging it
    once per configuration would weight it by how many systems agreed, which is
    the opposite of what a blind label is for."""
    independent.add_question(conn, GROUP, "which branch does it deploy from")
    question = independent.questions(conn, GROUP)[0]
    independent.run_configurations(
        conn, GROUP, question, _embedder(),
        {"shipping": {}, "vector only": {"vector_only": True}},
    )

    pool = independent.pool(conn, question["id"])

    assert len(pool) == len(set(pool))


def test_one_label_serves_every_configuration(conn):
    """Relevance is stored for a (question, fact) pair, never for a
    (question, configuration) pair. That is what makes the judging blind: there
    is nowhere for a system's identity to enter a label."""
    independent.add_question(conn, GROUP, "which branch does it deploy from")
    question = independent.questions(conn, GROUP)[0]
    independent.run_configurations(
        conn, GROUP, question, _embedder(),
        {"shipping": {}, "vector only": {"vector_only": True}},
    )
    edge_id = independent.pool(conn, question["id"])[0]

    independent.judge(conn, question["id"], edge_id, True, judged_by="someone")

    columns = {
        r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'eval_judgement'"
        ).fetchall()
    }
    assert "configuration" not in columns
    assert independent.pool(conn, question["id"]) == [
        e for e in independent.pool(conn, question["id"]) if e != edge_id
    ], "a judged fact must not be offered again"


def test_coverage_says_pooled_until_the_grid_is_complete(conn):
    """The caveat is a measurement, not a disclaimer. At web scale the grid is
    unjudgeable and pooling bias is permanent; on a store of a few hundred
    facts it can be closed, and the only honest way to say which applies is to
    count."""
    independent.add_question(conn, GROUP, "which branch does it deploy from")
    question = independent.questions(conn, GROUP)[0]
    independent.run_configurations(conn, GROUP, question, _embedder(), {"shipping": {}})

    partial = independent.coverage(conn, GROUP)
    assert partial["complete"] is False
    assert "POOLED" in independent.render(independent.score(conn, GROUP), partial)

    for edge_id in independent.pool(conn, question["id"]):
        independent.judge(conn, question["id"], edge_id, False)
    # Everything the configuration did not return, too.
    import json as _json

    from echo_memory.infra.db import GRAPH_NAME as GRAPH
    every = [
        str(r[0]) for r in conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH ()-[e:FACT]->() WHERE e.group_id = $g AND e.t_invalid IS NULL
                RETURN id(e) $$, %s) AS (i agtype)""",
            (_json.dumps({"g": GROUP}),),
        ).fetchall()
    ]
    for edge_id in every:
        independent.judge(conn, question["id"], edge_id, False)

    complete = independent.coverage(conn, GROUP)
    assert complete["complete"] is True
    text = independent.render(independent.score(conn, GROUP), complete)
    assert "recall over the store" in text
    assert "POOLED" not in text


def test_a_marked_file_is_read_back_and_blanks_stay_unjudged():
    """Judging moved to a file because a terminal prompt needs a TTY, cannot be
    paused inside a session, and puts a judge under exactly the time pressure
    that produces labels nobody should build on. A blank is not a verdict."""
    text = """
Q7: does it matter
[y] 1125899906842870  Apache AGE drops a property whose value is null
[n] 1125899906842820  Real per-node cost for the eco-credit dev environment
[ ] 1125899906842827  node_embedding.node_id is AGE's graphid type
"""
    seen = []

    class _Conn:
        def execute(self, *args):
            seen.append(args)
            return self

    counts = independent.import_pool(_Conn(), text, judged_by="someone")

    assert counts == {"y": 1, "n": 1, "skipped": 1}
    assert len(seen) == 2, "only the marked rows are written"


def _two_judges(conn):
    """One question, opened, with both judges having labelled its whole pool."""
    independent.add_question(conn, GROUP, "which branch does it deploy from")
    question = independent.questions(conn, GROUP)[0]
    independent.run_configurations(
        conn, GROUP, question, _embedder(),
        {"shipping": {}, "vector only": {"vector_only": True}},
    )
    ids = independent.pool(conn, question["id"])
    for edge_id in ids:
        independent.judge(conn, question["id"], edge_id, False, judged_by="first")
    # The second judge is more generous, which is the direction two judges
    # actually differed in: 11 of 142 pairs, every one of them first-says-no.
    for edge_id in ids:
        independent.judge(conn, question["id"], edge_id, True, judged_by="second")
    return question, ids


def test_scoring_refuses_to_pool_two_judges(conn):
    """Averaging two label sets is not a third measurement. A pair both judges
    labelled would count twice and a pair one judge labelled once, weighting a
    fact by how many people happened to look at it. Before this, score() took
    whichever row Postgres returned last."""
    _two_judges(conn)

    with pytest.raises(ValueError) as caught:
        independent.score(conn, GROUP)

    assert "first" in str(caught.value) and "second" in str(caught.value)


def test_one_judge_needs_no_naming(conn):
    """Refusing when there is only one judge would be ceremony: there is no
    choice to make and no way to make it silently."""
    independent.add_question(conn, GROUP, "which branch does it deploy from")
    question = independent.questions(conn, GROUP)[0]
    independent.run_configurations(conn, GROUP, question, _embedder(), {"shipping": {}})
    for edge_id in independent.pool(conn, question["id"]):
        independent.judge(conn, question["id"], edge_id, True, judged_by="only-one")

    assert independent.score(conn, GROUP)["shipping"]["judged_by"] == "only-one"


def test_each_judge_scores_to_their_own_labels(conn):
    """The whole point of keeping both: two judges over one pool are two
    results, and the difference between them is itself a finding."""
    _two_judges(conn)

    strict = independent.score(conn, GROUP, judged_by="first")["shipping"]
    generous = independent.score(conn, GROUP, judged_by="second")["shipping"]

    assert strict["questions"] == 0, "no relevant fact, so nothing to rank"
    assert generous["precision_at"][1] == 1.0
    assert strict["judged_by"] == "first" and generous["judged_by"] == "second"


def test_coverage_cannot_exceed_the_grid_by_adding_judges(conn):
    """Counting every judgement row made this report 2942 of 2850 pairs judged
    and print that pooling bias was closed. A count larger than the grid is not
    a rounding problem, it is the wrong denominator for the claim being made."""
    _two_judges(conn)

    for who in ("first", "second"):
        cover = independent.coverage(conn, GROUP, judged_by=who)
        assert cover["judged"] <= cover["possible"]
        assert cover["judged_by"] == who


def test_a_fresh_judge_gets_the_whole_pool_back(conn):
    """pool() promised the same pool could be presented twice for an agreement
    check while excluding everything anybody had judged, so the second judge
    got nothing and the second pass had to be built outside the tool."""
    question, ids = _two_judges(conn)

    assert independent.pool(conn, question["id"], judged_by="first") == []
    assert sorted(independent.pool(conn, question["id"], judged_by="third")) == sorted(ids)


def test_agreement_is_kappa_because_raw_agreement_flatters(conn):
    """Two judges who both say no to almost everything agree almost always.
    Kappa takes out the agreement the marginals alone would produce."""
    _question, ids = _two_judges(conn)

    result = independent.agreement(conn, GROUP, "first", "second")

    assert result["pairs"] == len(ids)
    assert result["raw_agreement"] == 0.0, "they disagreed on every pair"
    assert result["kappa"] <= 0.0

def test_a_ranking_flip_between_judges_is_reported_with_its_interval(conn):
    """The reason the comparison exists. Two judges put two configurations in
    opposite orders on MRR; without an interval that reads as a finding about
    the configurations rather than about how few questions there are."""
    independent.add_question(conn, GROUP, "which branch does it deploy from")
    question = independent.questions(conn, GROUP)[0]
    independent.run_configurations(
        conn, GROUP, question, _embedder(),
        {"shipping": {}, "vector only": {"vector_only": True}},
    )
    for edge_id in independent.pool(conn, question["id"]):
        independent.judge(conn, question["id"], edge_id, True, judged_by="only-one")

    result = independent.compare_configurations(
        conn, GROUP, "shipping", "vector only", judged_by="only-one"
    )

    assert result["questions"] == 1
    assert result["low"] <= result["delta"] <= result["high"]
    assert result["judged_by"] == "only-one"


def test_comparing_needs_a_judge_named_when_there_are_two(conn):
    """It reads per-question labels, so it inherits the same refusal."""
    _two_judges(conn)

    with pytest.raises(ValueError):
        independent.compare_configurations(conn, GROUP, "shipping", "vector only")
