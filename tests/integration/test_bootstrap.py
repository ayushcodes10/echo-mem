"""Bootstrap against a real database: queuing, the run-once guard, and the
first-query trigger that makes it automatic on a fresh install."""

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.cli.main import main
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect
from echo_memory.ingestion import bootstrap, capture


def _home(tmp_path):
    home = tmp_path / "home"
    work = tmp_path / "work" / "eigen"
    work.mkdir(parents=True, exist_ok=True)
    encoded = str(work).replace("/", "-")
    memory = home / ".claude" / "projects" / encoded / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    (memory / "loop.md").write_text("the remediation loop never recorded an outcome")
    (work / "CLAUDE.md").write_text("# eigen\n\nuse the deploy harness")
    return home


def test_bootstrap_queues_what_it_finds(migrated_db, tmp_path):
    conn = connect(migrated_db)

    result = bootstrap.run(conn, home=_home(tmp_path))

    assert result["skipped"] is False
    assert result["found"] == 2
    assert result["queued"] == 2
    assert result["by_project"] == {"eigen": 2}
    assert set(result["by_source"]) == {"claude-memory", "project-instructions"}


def test_queued_documents_carry_project_and_source(migrated_db, tmp_path):
    conn = connect(migrated_db)
    bootstrap.run(conn, home=_home(tmp_path))

    queued = capture.pending(conn)

    assert {q["project"] for q in queued} == {"eigen"}
    assert queued[0]["source"] == "claude-memory", "hand-written notes come first"


def test_it_runs_once(migrated_db, tmp_path):
    conn = connect(migrated_db)
    home = _home(tmp_path)

    first = bootstrap.run(conn, home=home)
    second = bootstrap.run(conn, home=home)

    assert first["skipped"] is False
    assert second["skipped"] is True
    assert bootstrap.has_run(conn) is True


def test_force_sweeps_again_and_picks_up_new_work(migrated_db, tmp_path):
    conn = connect(migrated_db)
    home = _home(tmp_path)
    bootstrap.run(conn, home=home)
    memory_dir = next((home / ".claude" / "projects").iterdir()) / "memory"
    (memory_dir / "later.md").write_text("something learned afterwards")

    again = bootstrap.run(conn, home=home, force=True)

    assert again["found"] == 3
    assert again["queued"] == 1, "only the genuinely new document should requeue"


def test_ingested_documents_do_not_come_back(migrated_db, tmp_path):
    conn = connect(migrated_db)
    bootstrap.run(conn, home=_home(tmp_path))
    paths = [q["path"] for q in capture.pending(conn)]
    capture.mark_ingested(conn, paths)

    bootstrap.run(conn, home=_home(tmp_path), force=True)

    assert capture.pending(conn) == []


def test_first_query_triggers_discovery(migrated_db, tmp_path, monkeypatch):
    """The whole point: a store initialised today should know about work done
    before it existed, without anyone having to ask."""
    monkeypatch.setattr(bootstrap.Path, "home", staticmethod(lambda: _home(tmp_path)))
    config = Config(user_id="ayush", agent_id="claude-code", database_url=migrated_db)
    server.startup(config=config, embedder=VectorEmbedder({"anything": REFERENCE}))

    result = server.query_memory("shared", query="anything")

    assert result["pending_ingest"]["count"] == 2
    assert "write_episode" in result["pending_ingest"]["instruction"]


def test_discovery_failure_never_breaks_recall(migrated_db, monkeypatch):
    def explode(*_args, **_kwargs):
        raise OSError("no such home")

    monkeypatch.setattr(bootstrap, "run", explode)
    config = Config(user_id="ayush", agent_id="claude-code", database_url=migrated_db)
    server.startup(config=config, embedder=VectorEmbedder({"anything": REFERENCE}))

    result = server.query_memory("shared", query="anything")

    assert "error" not in result
    assert "results" in result or "facts" in result


def test_cli_dry_run_queues_nothing(migrated_db, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", "ayush")
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", "claude-code")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", migrated_db)
    monkeypatch.setattr(bootstrap.Path, "home", staticmethod(lambda: _home(tmp_path)))

    assert main(["bootstrap", "--dry-run"]) == 0

    assert "Would queue 2 document(s)" in capsys.readouterr().out
    assert capture.pending(connect(migrated_db)) == []


def test_cli_bootstrap_reports_by_source_and_project(migrated_db, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", "ayush")
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", "claude-code")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", migrated_db)
    monkeypatch.setattr(bootstrap.Path, "home", staticmethod(lambda: _home(tmp_path)))

    assert main(["bootstrap"]) == 0

    out = capsys.readouterr().out
    assert "Found 2 existing document(s); 2 newly queued." in out
    assert "claude-memory" in out and "eigen" in out
    assert "never calls one" in out, "should be explicit that queuing is not ingesting"
