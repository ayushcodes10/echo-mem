"""The project/agent dimension end to end: written onto every fact, readable
back through the dashboard payload, reattributable for facts that predate it,
and queued for capture. See conftest.py for the migrated_db fixture."""

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.cli.dashboard import fetch_dashboard
from echo_memory.cli.dashboard_html import render_dashboard
from echo_memory.cli.main import main
from echo_memory.cli.reattribute import reattribute, sessions_by_project
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect
from echo_memory.ingestion import capture


def _config(migrated_db, project="eigen"):
    return Config(
        user_id="ayush", agent_id="claude-code", database_url=migrated_db, project=project
    )


def _seed(migrated_db, project="eigen", agent_id="claude-code", session="sess-1"):
    config = Config(
        user_id="ayush", agent_id=agent_id, database_url=migrated_db, project=project
    )
    embedder = VectorEmbedder(
        {
            "Eigon": REFERENCE, "remediation loop": REFERENCE, "Postgres": REFERENCE,
            "the loop never recorded an outcome": REFERENCE,
            "the loop now records outcomes": REFERENCE,
        }
    )
    server.startup(config=config, embedder=embedder)
    server.write_episode(
        "shared", session,
        [{"name": "Eigon", "type": "product"}, {"name": "remediation loop", "type": "component"}],
        [{"source": "Eigon", "target": "remediation loop", "relation_type": "has",
          "fact": "the loop never recorded an outcome", "confidence": "extracted"}],
    )
    return config


def test_every_fact_records_its_project_and_agent(migrated_db):
    config = _seed(migrated_db, project="eigen", agent_id="claude-code")
    conn = connect(migrated_db)

    facts = fetch_dashboard(conn, config)["scopes"]["shared"]["facts"]

    assert len(facts) == 1
    assert facts[0]["project"] == "eigen"
    assert facts[0]["agent_id"] == "claude-code"
    assert facts[0]["session_id"] == "sess-1"


def test_agent_is_recoverable_in_shared_scope(migrated_db):
    """The reason agent_id exists: shared group_id is user:X:shared, so before
    0003 the writing agent was unrecoverable in exactly the scope where more
    than one agent writes."""
    config = _seed(migrated_db, agent_id="cursor")
    conn = connect(migrated_db)

    facts = fetch_dashboard(conn, config)["scopes"]["shared"]["facts"]

    assert "shared" in config.group_id("shared")
    assert "cursor" not in config.group_id("shared")
    assert facts[0]["agent_id"] == "cursor"


def test_projects_are_listed_across_scopes(migrated_db):
    config = _seed(migrated_db, project="eigen")
    conn = connect(migrated_db)

    assert fetch_dashboard(conn, config)["projects"] == ["eigen"]


def test_reattribute_moves_a_session_off_unknown(migrated_db):
    config = _seed(migrated_db, project="unknown")
    conn = connect(migrated_db)
    group_id = config.group_id("shared")

    before = sessions_by_project(conn, group_id)
    changed = reattribute(conn, group_id, "sess-1", "eigen")
    after = sessions_by_project(conn, group_id)

    assert before[0]["project"] == "unknown"
    assert changed == 1
    assert after[0]["project"] == "eigen"


def test_reattribute_leaves_other_sessions_alone(migrated_db):
    config = _seed(migrated_db, project="unknown", session="sess-1")
    conn = connect(migrated_db)
    group_id = config.group_id("shared")
    server.write_episode(
        "shared", "sess-2",
        [{"name": "Eigon", "type": "product"}, {"name": "Postgres", "type": "tool"}],
        [{"source": "Eigon", "target": "Postgres", "relation_type": "uses",
          "fact": "the loop now records outcomes", "confidence": "extracted"}],
    )

    reattribute(conn, group_id, "sess-1", "eigen")

    by_session = {s["session_id"]: s["project"] for s in sessions_by_project(conn, group_id)}
    assert by_session["sess-1"] == "eigen"
    assert by_session["sess-2"] == "unknown"


def test_dashboard_payload_carries_what_an_edge_needs_to_answer(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)

    data = fetch_dashboard(conn, config)
    fact = data["scopes"]["shared"]["facts"][0]

    # what / when / who / where, all on the edge itself
    assert fact["fact"] and fact["relation_type"] and fact["confidence"]
    assert fact["t_valid"] and fact["t_invalid"] is None
    assert fact["agent_id"] and fact["session_id"]
    assert fact["project"] == "eigen"
    # why: the audit trail, indexed by the edge it touches
    assert data["scopes"]["shared"]["audit_by_edge"][fact["id"]][0]["mutation_type"] == "created"


def test_superseded_facts_are_kept_for_the_history_panel(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    server.write_episode(
        "shared", "sess-2",
        [{"name": "Eigon", "type": "product"}, {"name": "remediation loop", "type": "component"}],
        [{"source": "Eigon", "target": "remediation loop", "relation_type": "has",
          "fact": "the loop now records outcomes", "confidence": "extracted"}],
    )

    facts = fetch_dashboard(conn, config)["scopes"]["shared"]["facts"]

    assert len(facts) == 2
    assert sum(1 for f in facts if f["t_invalid"] is not None) == 1


def test_rendered_dashboard_is_self_contained_and_embeds_the_data(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)

    html = render_dashboard(fetch_dashboard(conn, config))

    assert html.startswith("<!doctype html>")
    assert "the loop never recorded an outcome" in html
    assert "eigen" in html
    # no external asset beyond the font stylesheet
    assert html.count("http") == html.count("https://fonts.")


def test_capture_queue_notices_and_closes(migrated_db, tmp_path):
    conn = connect(migrated_db)
    memory = tmp_path / "eigon-loop.md"
    memory.write_text("the loop never recorded an outcome")

    first = capture.notice_file(conn, memory, "eigen")
    again = capture.notice_file(conn, memory, "eigen")
    queued = capture.pending(conn)

    assert first["changed"] is True
    assert again["changed"] is False, "re-noticing an unchanged file should not requeue it"
    assert [q["path"] for q in queued] == [str(memory)]

    capture.mark_ingested(conn, [str(memory)])
    assert capture.pending(conn) == []


def test_a_changed_memory_file_reopens_its_queue_entry(migrated_db, tmp_path):
    conn = connect(migrated_db)
    memory = tmp_path / "eigon-loop.md"
    memory.write_text("first version")
    capture.notice_file(conn, memory, "eigen")
    capture.mark_ingested(conn, [str(memory)])

    memory.write_text("a later version saying something new")
    capture.notice_file(conn, memory, "eigen")

    assert [q["path"] for q in capture.pending(conn)] == [str(memory)]


def test_cli_pending_lists_then_closes(migrated_db, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", "ayush")
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", "claude-code")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", migrated_db)
    memory = tmp_path / ".claude" / "projects" / "-Users-ayush-work-eigen" / "memory" / "loop.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("the loop never recorded an outcome")

    assert main(["notice", str(memory)]) == 0
    assert main(["pending"]) == 0
    out = capsys.readouterr().out
    assert "  eigen\n" in out, "project should come from the memory file's own path, not cwd"

    assert main(["pending", "--done", str(memory)]) == 0
    assert main(["pending"]) == 0
    assert "Nothing pending" in capsys.readouterr().out


def test_cli_dashboard_writes_a_file(migrated_db, tmp_path, monkeypatch, capsys):
    config = _seed(migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)
    out = tmp_path / "dash.html"

    assert main(["dashboard", "--out", str(out)]) == 0

    assert "<!doctype html>" in out.read_text()
    assert "facts across" in capsys.readouterr().out


def test_cli_reattribute_without_arguments_lists_and_fails(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db, project="unknown")
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)

    exit_code = main(["--scope", "shared", "reattribute"])

    assert exit_code == 1
    assert "session sess-1" in capsys.readouterr().out
