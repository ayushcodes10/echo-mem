"""A session that works hard and records nothing has to be visible.

The Stop gate held a session open until the memory files it wrote were in the
graph, and that left the larger failure untouched: a session that writes no
memory file has an empty queue, which reads as nothing owed. Both measured
failures went by exactly that way, with the gate installed and firing - eight
merged PRs in one window, and two days of building echo-mem-cloud whose
constraints reached commit messages and READMEs and never reached memory. A
Codex session hunting for that work made twenty query_memory calls and
correctly found nothing.

A hook can only fire on an artefact, and here the artefact is the work itself.
So edits are counted, and paired with the audit log's existing per-session fact
record, "worked hard and recorded nothing" becomes a question the gate can ask.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.cli import stop_gate
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect
from echo_memory.ingestion import activity
from echo_memory.ingestion.write_episode import write_episode

PROJECT = "echo-mem"
GROUP = "user:ayush:shared"
SESSION = "s-worked-a-lot"
FACT = "the deploy branch is master, never main"


@pytest.fixture()
def empty_projects(tmp_path, monkeypatch):
    """gate() sweeps the filesystem before asking, so without this the real
    ~/.claude/projects is scanned and the FILE gate fires on the author's own
    memory files - which would test the old path while claiming to test the new
    one. Same override reconcile already takes for the same reason."""
    monkeypatch.setenv("ECHO_MEMORY_CLAUDE_PROJECTS", str(tmp_path))
    return tmp_path


def _config(url):
    return Config(user_id="ayush", agent_id="claude-code", database_url=url, project=PROJECT)


def _args(session_id=SESSION):
    return SimpleNamespace(session_id=session_id, hook_json=False)


def _edits(conn, n, session_id=SESSION):
    for _ in range(n):
        activity.record_edit(conn, session_id, PROJECT)


def _write_a_fact(conn, session_id=SESSION):
    write_episode(
        conn, GROUP, session_id,
        [{"name": "deploy branch", "type": "policy"}],
        [{"source": "deploy branch", "target": "deploy branch", "relation_type": "is",
          "fact": FACT, "confidence": "extracted"}],
        {"deploy branch": {"resolved_to": "new"}},
        VectorEmbedder({"deploy branch": REFERENCE, FACT: REFERENCE}),
        agent_id="claude-code",
    )


def test_substantial_work_with_no_facts_is_flagged(migrated_db):
    """The case the gate could not see."""
    with connect(migrated_db) as conn:
        _edits(conn, activity.MIN_EDITS_TO_ASK)
        work = activity.worked_without_recording(conn, SESSION)

    assert work["edits"] == activity.MIN_EDITS_TO_ASK
    assert work["facts"] == 0
    assert work["should_ask"]


def test_a_session_that_recorded_something_is_left_alone(migrated_db):
    """One fact is enough. The gate asks whether anything was captured, not
    whether enough was - judging sufficiency is not something a counter can do,
    and guessing at it is how a gate becomes noise."""
    with connect(migrated_db) as conn:
        _edits(conn, 20)
        _write_a_fact(conn)
        work = activity.worked_without_recording(conn, SESSION)

    assert work["facts"] >= 1
    assert not work["should_ask"]


def test_a_small_session_is_not_interrupted(migrated_db):
    """A one or two file session is a typo fix or a rename. The MCP tool
    description already tells agents to skip those, and a gate that fires on
    them teaches people to disable it - which is precisely how the SessionStart
    briefing lost."""
    with connect(migrated_db) as conn:
        _edits(conn, activity.MIN_EDITS_TO_ASK - 1)
        assert not activity.worked_without_recording(conn, SESSION)["should_ask"]


def test_edits_are_counted_per_session(migrated_db):
    """Another session's work must not hold this one open."""
    with connect(migrated_db) as conn:
        _edits(conn, 10, session_id="other-session")
        assert activity.edits_by(conn, SESSION) == 0
        assert not activity.worked_without_recording(conn, SESSION)["should_ask"]


def test_the_gate_asks_when_there_are_no_queued_files(migrated_db, capsys, empty_projects):
    """End to end, through run(). An empty queue used to mean silence; it now
    means the other question gets asked, and this asserts on what the hook
    actually prints rather than on the renderer in isolation."""
    with connect(migrated_db) as conn:
        _edits(conn, 12)
        assert stop_gate.run(_args(), _config(migrated_db), conn) == 0

    printed = capsys.readouterr().out
    assert "12 files" in printed, f"the gate said nothing: {printed!r}"
    assert "write_episode" in printed


def test_the_gate_stays_silent_for_a_session_that_recorded(
    migrated_db, capsys, empty_projects
):
    """The steady state has to be no output at all, or the gate becomes noise
    and gets switched off."""
    with connect(migrated_db) as conn:
        _edits(conn, 12)
        _write_a_fact(conn)
        assert stop_gate.run(_args(), _config(migrated_db), conn) == 0

    assert capsys.readouterr().out == ""


def test_the_reason_names_the_count_and_offers_a_way_out(migrated_db):
    """A claim with the number attached is checkable by the agent reading it.
    And a gate with no honest exit is one people switch off - 'nothing durable
    happened' has to be a real answer."""
    reason = stop_gate.render_unrecorded_reason({"edits": 14, "facts": 0})

    assert "14 files" in reason
    assert "nothing durable" in reason
    assert "write_episode" in reason


def test_it_fires_at_most_once_per_session(migrated_db, empty_projects):
    """Same bound as the file gate. An eigen session hit that one five times on
    2026-09-02 and spent 27 minutes unable to satisfy any of them."""
    config = _config(migrated_db)
    with connect(migrated_db) as conn:
        _edits(conn, 12)
        stop_gate.run(_args(), config, conn)
        assert stop_gate.already_gated(conn, SESSION)
        # Second stop: the session is recorded as gated, so it returns silently.
        assert stop_gate.run(_args(), config, conn) == 0
