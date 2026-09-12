"""Knowledge health.

The command exists because a store can look healthy by every number the CLI
reported - 160 facts, 24 projects, no duplicates, no bad merges - while 142 of
those facts were bulk imports, the last real write was six days old, and one of
two wired agents had never written anything. Each was in the data; none was
surfaced. These tests pin the three that hid."""

import pytest

from echo_memory.cli import health

BASE = {
    "nodes": 100, "facts": 100, "organic_writes": 100, "imported_writes": 0,
    "last_write": "2026-08-29", "days_since_write": 0,
    "writers": {"claude-code": 60, "cursor": 40}, "silent_agents": [],
    "orphans": [], "components": 4, "clusters": 8,
    "unreviewed_pairs": 2, "unattributed_facts": 0,
    "duplicates": 0, "bad_merges": 0,
    "reads": {"days": 7, "reads": 0, "reads_with_facts": 0,
              "injected_chars": 0, "injected_tokens": 0, "saves": 0},
}


def h(**over):
    return {**BASE, **over}


def test_a_healthy_store_scores_high_and_has_nothing_to_flag():
    assert health.score(h()) >= 90
    _, attention, _ = health.findings(h())
    assert attention == []


def test_an_empty_store_scores_zero_rather_than_perfect():
    """Nothing wrong is not the same as nothing there. A store with no facts
    would otherwise trip none of the deductions and score 100."""
    assert health.score(h(facts=0, nodes=0, organic_writes=0)) == 0


def test_silence_is_penalised_and_grows_with_time():
    recent = health.score(h(days_since_write=3))
    week = health.score(h(days_since_write=10))
    month = health.score(h(days_since_write=40))

    assert recent > week > month
    assert recent == health.score(h()), "under the threshold costs nothing"


def test_a_single_writer_is_flagged_because_recall_cannot_be_cross_tool():
    _, attention, rec = health.findings(h(writers={"claude-code": 100}))

    assert any("only claude-code has ever written" in a for a in attention)
    assert any("adopt" in r for r in rec)


def test_a_store_that_has_never_been_written_to_reads_as_a_sentence():
    """`only nothing has ever written` was the first draft."""
    _, attention, _ = health.findings(h(writers={}, facts=0, organic_writes=0))

    assert not any("only nothing" in a for a in attention)


def test_imports_outnumbering_real_writes_is_surfaced():
    """The illusion that made a six-day-silent store look busy."""
    _, attention, _ = health.findings(h(organic_writes=18, imported_writes=142))

    assert any("bulk import" in a for a in attention)


def test_a_wired_client_that_never_writes_is_named():
    _, attention, rec = health.findings(h(silent_agents=["cursor"]))

    assert any("cursor" in a for a in attention)
    assert any("skill" in r for r in rec)


def test_unattributed_facts_are_flagged_without_unfollowable_advice():
    """These used to be reported with "run `alembic upgrade head`". Two things
    are wrong with that. Migration 0011 is what produces this state, so once it
    has run the advice changes nothing - and a pip-installed user has no
    alembic.ini at all, so the command cannot even start (see cli/initdb.py).
    What is actionable is stopping the supply: a long-running MCP client keeps
    the code it imported at spawn, so it goes on writing the old shape."""
    _, attention, rec = health.findings(h(unattributed_facts=58))

    assert any("no recorded author" in a for a in attention)
    assert not any("alembic" in r for r in rec), (
        "a pip install has no alembic.ini; this command cannot be run"
    )
    assert any("restart" in r.lower() for r in rec)


@pytest.mark.parametrize("field,value", [
    ("duplicates", 3), ("bad_merges", 2), ("unattributed_facts", 20),
])
def test_confirmed_defects_cost_more_than_untidiness(field, value):
    assert health.score(h(**{field: value})) < health.score(h())


def test_the_score_never_leaves_its_range():
    worst = h(facts=1, nodes=1, organic_writes=0, days_since_write=999,
              writers={}, silent_agents=["a", "b"], orphans=[{"name": "x", "type": "y"}],
              unreviewed_pairs=500, unattributed_facts=500, duplicates=9, bad_merges=9)

    assert 0 <= health.score(worst) <= 100
    assert 0 <= health.score(h()) <= 100


def test_every_attention_item_comes_with_something_to_do():
    """A diagnostic that does not tell you the next move is a complaint."""
    _, attention, rec = health.findings(
        h(writers={"claude-code": 1}, silent_agents=["cursor"],
          unreviewed_pairs=90, unattributed_facts=5, days_since_write=30)
    )

    assert len(attention) >= 4
    assert len(rec) >= 4


def test_render_shows_the_last_real_write_even_when_it_is_not_a_warning():
    """A threshold decides when to complain, not whether the reader sees the
    number."""
    text = health.render(h(days_since_write=1, organic_writes=18,
                           last_write="2026-08-29"))

    assert "18 written while working" in text
    assert "2026-08-29" in text


def test_read_volume_with_no_saves_is_flagged_as_an_open_question():
    """The product's central claim is that recall earns what it costs. Real read
    volume producing no recorded save does not prove it fails - it proves nobody
    can tell, and the two need different fixes."""
    _, attention, rec = health.findings(h(reads={
        "days": 7, "reads": 340, "reads_with_facts": 300,
        "injected_chars": 440000, "injected_tokens": 110000, "saves": 0,
    }))

    assert any("produced no recorded save" in a for a in attention)
    assert any("different fixes" in r for r in rec)


def test_reads_with_saves_are_not_flagged():
    _, attention, _ = health.findings(h(reads={
        "days": 7, "reads": 340, "reads_with_facts": 300,
        "injected_chars": 440000, "injected_tokens": 110000, "saves": 4,
    }))

    assert not any("no recorded save" in a for a in attention)


def test_render_states_the_cost_alongside_the_benefit():
    text = health.render(h(reads={
        "days": 7, "reads": 340, "reads_with_facts": 306,
        "injected_chars": 440000, "injected_tokens": 110000, "saves": 12,
    }))

    assert "read 340 times in 7d" in text
    assert "90% returned something" in text
    assert "110,000 tokens injected" in text
    assert "12 save(s) recorded" in text


def test_a_store_with_no_reads_says_so_rather_than_dividing_by_zero():
    text = health.render(h(reads={
        "days": 7, "reads": 0, "reads_with_facts": 0,
        "injected_chars": 0, "injected_tokens": 0, "saves": 0,
    }))

    assert "no reads recorded in 7d" in text


# --- the writer that is not the code on disk ----------------------------------


def test_a_stale_writer_is_named_first_and_explained():
    """An MCP stdio server holds the code it imported at spawn, so upgrading the
    package changes nothing until the client restarts. That gap cost this store
    30 facts with no author and 7 with no project, and nothing anywhere said so.

    First in the list because it explains other findings rather than adding to
    them: every other line is describing the stale writer's output."""
    _, attention, rec = health.findings(h(stale_writer="0.1.0"))

    assert attention[0].startswith("the last write came from version 0.1.0")
    assert any("Restart the client" in r for r in rec)


def test_a_current_writer_says_nothing():
    """The steady state is silence. A version line on every run is noise that
    teaches people to skip the section it lives in."""
    attention = health.findings(h(stale_writer=None))[1]

    assert not any("version" in a for a in attention)


def test_the_gate_line_separates_three_outcomes_not_two():
    """A firing that resolved by closing an already-recorded document is not a
    failure, and neither is one where nothing was demonstrably owed. The first
    version of this metric counted only new writes and reported 1 of 8, which a
    reviewer identified as the wrong success definition while the paper quoting
    it also said so.

    Edit count is evidence of ACTIVITY, not of an unmet need to remember. A
    session with 118 edits and no facts looks damning and establishes nothing
    about whether anything in those edits was worth keeping, so the remainder
    is named unresolved rather than counted against the mechanism."""
    out = health.render(h(
        gate={"fired": 8, "converted": 1, "wrote": 1, "closed": 0, "with_queue": 4}
    ))

    assert "1 wrote a fact" in out
    assert "0 closed a queued document" in out
    assert "7 unresolved" in out
    assert "4 of 8 fired with something queued" in out
    assert "not established" in out
