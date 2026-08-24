"""The session-start briefing.

Why it exists: `write_episode` is discretionary, and the "work is queued" nudge
used to live inside `query_memory`'s response - so an agent only learned memory
existed if it had already used memory. A session that called neither tool heard
nothing. Two days of real use produced zero organic writes. SessionStart is the
one moment guaranteed to happen in every session, and Claude Code injects
additionalContext deterministically rather than leaving it to the model."""

import json

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.cli import session_start
from echo_memory.cli.main import main
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect
from echo_memory.ingestion import capture


def _seed(migrated_db, project="eigen"):
    config = Config(
        user_id="ayush", agent_id="claude-code", database_url=migrated_db, project=project
    )
    server.startup(
        config=config,
        embedder=VectorEmbedder(
            {
                "Eigon": REFERENCE, "remediation loop": REFERENCE,
                "the loop never recorded an outcome": REFERENCE,
            }
        ),
    )
    server.write_episode(
        "shared", "sess-1",
        [{"name": "Eigon", "type": "product"},
         {"name": "remediation loop", "type": "component"}],
        [{"source": "Eigon", "target": "remediation loop", "relation_type": "has",
          "fact": "the loop never recorded an outcome", "confidence": "extracted"}],
    )
    return config


def test_the_brief_reports_facts_for_this_project(migrated_db):
    config = _seed(migrated_db, project="eigen")

    brief = session_start.build_brief(connect(migrated_db), config, "eigen")

    assert brief["project"] == "eigen"
    assert brief["n_facts"] == 1
    assert brief["recent"][0]["source"] == "Eigon"


def test_another_projects_facts_are_not_in_this_projects_brief(migrated_db):
    """The briefing lands in every session; a dugout session should not be
    handed eigen's memory as context it has to skim past."""
    config = _seed(migrated_db, project="eigen")

    brief = session_start.build_brief(connect(migrated_db), config, "dugout")

    assert brief["n_facts"] == 0


def test_an_empty_project_still_says_memory_is_available(migrated_db):
    config = _seed(migrated_db, project="eigen")

    text = session_start.render_brief(
        session_start.build_brief(connect(migrated_db), config, "brand-new")
    )

    assert "nothing recorded yet" in text
    assert "query_memory" in text


def test_the_brief_surfaces_the_pending_queue(migrated_db, tmp_path):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    memory = tmp_path / "note.md"
    memory.write_text("something learned")
    capture.notice_file(conn, memory, "dugout")

    brief = session_start.build_brief(conn, config, "eigen")

    assert brief["n_pending"] == 1
    assert brief["pending_projects"] == ["dugout"]
    assert "queued but not yet recorded" in session_start.render_brief(brief)


def test_the_brief_always_says_when_to_write(migrated_db):
    config = _seed(migrated_db)

    text = session_start.render_brief(
        session_start.build_brief(connect(migrated_db), config, "eigen")
    )

    assert "write_episode" in text
    assert "record_recall_save" in text
    assert "in the same turn" in text


def test_long_facts_are_truncated_so_the_brief_stays_a_paragraph(migrated_db):
    """This lands in every session's context whether or not it turns out to be
    relevant, so it pays rent by being brief."""
    config = _seed(migrated_db)
    brief = session_start.build_brief(connect(migrated_db), config, "eigen")
    brief["recent"][0]["fact"] = "x" * 500

    text = session_start.render_brief(brief)

    assert "..." in text
    assert "x" * 300 not in text


def test_hook_output_is_the_shape_claude_code_reads(migrated_db):
    payload = json.loads(session_start.render_hook_output("some context"))

    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert payload["hookSpecificOutput"]["additionalContext"] == "some context"


def test_cli_emits_plain_text_by_default(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)

    assert main(["session-brief", "--project", "eigen"]) == 0

    out = capsys.readouterr().out
    assert "Echo Memory has 1 fact(s)" in out
    assert not out.startswith("{")


def test_cli_emits_hook_json_on_request(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)

    assert main(["session-brief", "--project", "eigen", "--hook-json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
