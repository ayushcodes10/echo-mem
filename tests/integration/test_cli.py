"""End-to-end tests for the echo-memory CLI (get_fact_history, export_group,
and main()'s argv dispatch) against a real Postgres+AGE+pgvector database.
See conftest.py for the migrated_db fixture and DB-reachability skip."""

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.audit.get_audit_log import get_fact_history
from echo_memory.cli.export import export_group
from echo_memory.cli.main import main
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect


def _seed(migrated_db):
    config = Config(user_id="ayush", agent_id="claude-code", database_url=migrated_db)
    embedder = VectorEmbedder(
        {
            "Postgres": REFERENCE,
            "Decision": REFERENCE,
            "using SQLite for now": REFERENCE,
            "switched to Postgres for durability": REFERENCE,
        }
    )
    server.startup(config=config, embedder=embedder)
    r1 = server.write_episode(
        "shared", "sess-1",
        [{"name": "Postgres", "type": "tool"}, {"name": "Decision", "type": "decision"}],
        [
            {"source": "Decision", "target": "Postgres", "relation_type": "uses",
             "fact": "using SQLite for now", "confidence": "extracted"}
        ],
    )
    server.write_episode(
        "shared", "sess-2",
        [{"name": "Postgres", "type": "tool"}, {"name": "Decision", "type": "decision"}],
        [
            {"source": "Decision", "target": "Postgres", "relation_type": "uses",
             "fact": "switched to Postgres for durability", "confidence": "extracted"}
        ],
    )
    return config, r1["edges_created"][0]


def test_get_fact_history_traces_a_superseded_fact(migrated_db):
    config, old_fact_id = _seed(migrated_db)
    conn = connect(migrated_db)

    result = get_fact_history(conn, config.group_id("shared"), old_fact_id)

    mutation_types = [e["mutation_type"] for e in result["entries"]]
    assert mutation_types == ["created", "fact_superseded"]


def test_export_group_writes_index_and_node_files(migrated_db, tmp_path):
    config, _ = _seed(migrated_db)
    conn = connect(migrated_db)

    result = export_group(conn, config.group_id("shared"), tmp_path)

    assert result["n_nodes"] == 2
    assert result["n_facts"] == 1  # only the active fact, superseded one excluded
    assert (tmp_path / "index.md").exists()
    assert (tmp_path / "postgres.md").exists()
    assert (tmp_path / "decision.md").exists()

    decision_content = (tmp_path / "decision.md").read_text()
    assert "switched to Postgres for durability" in decision_content
    assert "using SQLite for now" not in decision_content


def test_main_why_command(migrated_db, tmp_path, capsys, monkeypatch):
    config, old_fact_id = _seed(migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)

    exit_code = main(["--scope", "shared", "why", old_fact_id])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert f"History for fact {old_fact_id}:" in out
    assert "superseded by" in out


def test_main_export_command(migrated_db, tmp_path, capsys, monkeypatch):
    config, _ = _seed(migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)
    out_dir = tmp_path / "export"

    exit_code = main(["--scope", "shared", "export", "--out", str(out_dir)])

    assert exit_code == 0
    assert "Exported 2 nodes, 1 facts" in capsys.readouterr().out
    assert (out_dir / "index.md").exists()


def test_main_missing_env_returns_error_not_exception(monkeypatch, capsys):
    for var in ("ECHO_MEMORY_USER_ID", "ECHO_MEMORY_AGENT_ID", "ECHO_MEMORY_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)

    exit_code = main(["why", "123"])

    assert exit_code == 1
    assert "error" in capsys.readouterr().err
