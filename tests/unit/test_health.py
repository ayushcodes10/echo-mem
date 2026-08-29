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


def test_unattributed_facts_are_flagged_with_the_command_that_fixes_them():
    _, attention, rec = health.findings(h(unattributed_facts=58))

    assert any("no recorded author" in a for a in attention)
    assert any("alembic upgrade head" in r for r in rec)


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
