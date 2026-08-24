"""First-run project comprehension.

A first session in an existing project starts with an empty memory even though
the project is months old. This asks for one pass, once, and points at the
sources worth reading. The judgement stays with the agent; the server never
calls an LLM."""

from pathlib import Path

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.cli import analyse, session_start
from echo_memory.cli.main import main
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect


def _project(tmp_path, name="blank-project", **files):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def _config(migrated_db, project):
    return Config(
        user_id="ayush", agent_id="claude-code", database_url=migrated_db, project=project
    )


def test_graphify_report_is_offered_before_the_readme(tmp_path):
    """graphify's report is already a synthesis; a README is raw material."""
    root = _project(
        tmp_path,
        **{"README.md": "# thing", "graphify-out/GRAPH_REPORT.md": "# architecture"},
    )

    sources = analyse.find_sources(root)

    assert sources[0]["path"].endswith("GRAPH_REPORT.md")
    assert sources[1]["path"].endswith("README.md")


def test_only_sources_that_exist_are_offered(tmp_path):
    root = _project(tmp_path, **{"README.md": "# thing"})

    paths = [s["path"] for s in analyse.find_sources(root)]

    assert len(paths) == 1
    assert paths[0].endswith("README.md")


def test_a_docs_directory_lists_its_files(tmp_path):
    root = _project(
        tmp_path,
        **{"docs/designs/one.md": "a", "docs/designs/two.md": "b"},
    )

    sources = analyse.find_sources(root)

    assert sources[0]["is_dir"] is True
    assert len(sources[0]["files"]) == 2


def test_a_project_with_no_docs_still_gets_an_instruction(tmp_path):
    root = _project(tmp_path)

    text = analyse.render_instruction("bare", analyse.find_sources(root))

    assert "No README or docs found" in text
    assert "git log" in text


def test_the_instruction_asks_for_facts_not_an_inventory(tmp_path):
    """Code structure questions belong to graphify. Importing its 9,321-node
    graph here would bury every recorded decision under file names."""
    root = _project(tmp_path, **{"README.md": "# thing"})

    text = analyse.render_instruction("thing", analyse.find_sources(root))

    assert "facts, not an inventory" in text
    assert "graphify" in text
    assert str(analyse.SUGGESTED_MAX_FACTS) in text


def test_a_blank_project_is_asked_to_analyse(migrated_db, tmp_path):
    root = _project(tmp_path, **{"README.md": "# thing"})
    config = _config(migrated_db, "blank-project")

    brief = session_start.build_brief(connect(migrated_db), config, "blank-project", root)

    assert brief["needs_analysis"] is True
    assert brief["analysis_sources"]
    assert "comprehension pass" in session_start.render_brief(brief)


def test_a_project_with_facts_is_not_asked(migrated_db, tmp_path):
    """Writing anything stops the prompt, so an agent that forgets to mark the
    pass done cannot pile up duplicate passes next session."""
    config = _config(migrated_db, "eigen")
    server.startup(
        config=config,
        embedder=VectorEmbedder({"Eigon": REFERENCE, "a thing": REFERENCE,
                                 "eigen deploys from main": REFERENCE}),
    )
    server.write_episode(
        "shared", "s1",
        [{"name": "Eigon", "type": "product"}, {"name": "a thing", "type": "thing"}],
        [{"source": "Eigon", "target": "a thing", "relation_type": "uses",
          "fact": "eigen deploys from main", "confidence": "extracted"}],
    )

    brief = session_start.build_brief(
        connect(migrated_db), config, "eigen", _project(tmp_path)
    )

    assert brief["needs_analysis"] is False
    assert "comprehension pass" not in session_start.render_brief(brief)


def test_marking_it_done_stops_the_prompt(migrated_db, tmp_path):
    root = _project(tmp_path, **{"README.md": "# thing"})
    config = _config(migrated_db, "blank-project")
    conn = connect(migrated_db)

    before = session_start.build_brief(conn, config, "blank-project", root)
    analyse.mark_analysed(conn, "blank-project", 12, ["README.md"])
    after = session_start.build_brief(conn, config, "blank-project", root)

    assert before["needs_analysis"] is True
    assert after["needs_analysis"] is False


def test_marking_is_idempotent(migrated_db):
    conn = connect(migrated_db)

    analyse.mark_analysed(conn, "p", 5, ["a"])
    analyse.mark_analysed(conn, "p", 9, ["a", "b"])

    row = conn.execute(
        "SELECT n_facts, sources FROM public.project_analysis WHERE project = 'p'"
    ).fetchone()
    assert row[0] == 9
    assert row[1] == ["a", "b"]


def test_cli_prints_the_instruction(migrated_db, tmp_path, monkeypatch, capsys):
    root = _project(tmp_path, **{"README.md": "# thing"})
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", "ayush")
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", "claude-code")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", migrated_db)

    assert main(["analyse", "--project", "p", "--root", str(root)]) == 0

    assert "comprehension pass" in capsys.readouterr().out


def test_cli_done_records_the_pass(migrated_db, tmp_path, monkeypatch, capsys):
    root = _project(tmp_path, **{"README.md": "# thing"})
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", "ayush")
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", "claude-code")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", migrated_db)

    assert main(["analyse", "--project", "p", "--root", str(root), "--done"]) == 0

    assert "Recorded a comprehension pass" in capsys.readouterr().out
    assert analyse.has_been_analysed(connect(migrated_db), "p") is True


def test_cli_says_when_a_pass_already_ran(migrated_db, tmp_path, monkeypatch, capsys):
    root = _project(tmp_path, **{"README.md": "# thing"})
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", "ayush")
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", "claude-code")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", migrated_db)
    analyse.mark_analysed(connect(migrated_db), "p", 3, [])

    assert main(["analyse", "--project", "p", "--root", str(root)]) == 0

    assert "already had a comprehension pass" in capsys.readouterr().out


def test_paths_in_the_instruction_are_absolute(tmp_path):
    """The agent reads these from wherever it happens to be."""
    root = _project(tmp_path, **{"README.md": "# thing"})

    text = analyse.render_instruction("p", analyse.find_sources(root))

    assert str(root) in text
    assert Path(analyse.find_sources(root)[0]["path"]).is_absolute()
