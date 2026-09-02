"""The two mechanisms that make capture deterministic instead of instructional.

Between 2026-08-23 and 2026-09-02 the session-start briefing asked every session
to drain the capture queue. 16 memory files were written across eigen and dugout
in that window; the hook noticed all 16; none became facts in the session that
wrote them. The instruction was correct and was ignored 100% of the time.

So capture stopped being asked for. `reconcile` reads the filesystem instead of
trusting that the hook fired, and `stop-check` holds the session open instead of
reminding it. These tests pin the behaviours that make that safe to leave on."""

import json

from echo_memory.cli import reconcile, stop_gate
from echo_memory.cli.main import main
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect
from echo_memory.ingestion import capture


def _config(migrated_db, project="eigen"):
    return Config(
        user_id="ayush", agent_id="claude-code", database_url=migrated_db, project=project
    )


def _memory_file(root, encoded_project, name, text):
    d = root / encoded_project / "memory"
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    path.write_text(text)
    return path


def test_a_file_the_hook_never_saw_is_queued_by_the_sweep(migrated_db, tmp_path):
    conn = connect(migrated_db)
    _memory_file(tmp_path, "-Users-ayush-work-eigen", "pause.md", "the ALB listener was manual")

    result = reconcile.reconcile(conn, root=tmp_path)

    assert result["scanned"] == 1
    assert [item["project"] for item in result["new"]] == ["eigen"]
    assert [p["path"] for p in capture.pending(conn)] == [
        str(tmp_path / "-Users-ayush-work-eigen" / "memory" / "pause.md")
    ]


def test_a_file_edited_after_ingest_is_reopened(migrated_db, tmp_path):
    """The eigen bug, exactly. Noticed, ingested, then edited by a session
    whose hook did not fire - so the graph holds the old content and nothing
    knows the file has moved on."""
    conn = connect(migrated_db)
    path = _memory_file(tmp_path, "-Users-ayush-work-eigen", "pricing.md", "backend built")
    reconcile.reconcile(conn, root=tmp_path)
    capture.mark_ingested(conn, [str(path)])
    assert capture.pending(conn) == []

    path.write_text("backend built\n\nDONE: shipped, and GST has never run")
    result = reconcile.reconcile(conn, root=tmp_path)

    assert [item["project"] for item in result["changed"]] == ["eigen"]
    assert [p["path"] for p in capture.pending(conn)] == [str(path)]


def test_an_unchanged_file_is_not_reopened(migrated_db, tmp_path):
    conn = connect(migrated_db)
    path = _memory_file(tmp_path, "-Users-ayush-work-eigen", "pause.md", "unchanged")
    reconcile.reconcile(conn, root=tmp_path)
    capture.mark_ingested(conn, [str(path)])

    result = reconcile.reconcile(conn, root=tmp_path)

    # Without this the sweep would re-queue everything on every session start
    # and the queue would never be empty, which is the same as no queue.
    assert result["unchanged"] == 1
    assert result["new"] == [] and result["changed"] == []
    assert capture.pending(conn) == []


def test_the_gate_is_silent_when_this_project_owes_nothing(migrated_db, tmp_path):
    conn = connect(migrated_db)
    result = stop_gate.gate(conn, "eigen", root=tmp_path)
    assert result["n"] == 0


def test_the_gate_blocks_and_names_what_is_missing(migrated_db, tmp_path):
    conn = connect(migrated_db)
    _memory_file(tmp_path, "-Users-ayush-work-eigen", "pause.md", "the ALB listener was manual")

    result = stop_gate.gate(conn, "eigen", root=tmp_path)
    payload = json.loads(stop_gate.render_hook_output(result))

    assert result["n"] == 1
    assert payload["decision"] == "block"
    assert "pause.md" in payload["reason"]
    # The reason is the agent's next instruction, so it has to say what to call.
    assert "write_episode" in payload["reason"]
    assert "echo-memory pending --done" in payload["reason"]


def test_another_project_s_backlog_cannot_hold_this_session_open(migrated_db, tmp_path):
    conn = connect(migrated_db)
    _memory_file(tmp_path, "-Users-ayush-work-eigen", "pause.md", "eigen owes a fact")

    # Blocking an echo-mem session because eigen has a backlog is how a gate
    # gets switched off. Only this project's files can hold it.
    assert stop_gate.gate(conn, "dugout", root=tmp_path)["n"] == 0
    assert stop_gate.gate(conn, "eigen", root=tmp_path)["n"] == 1


def test_the_gate_sweeps_before_it_judges(migrated_db, tmp_path):
    """A file written moments ago through a path the capture hook did not match
    is not in the queue yet. The end of the session is the last chance."""
    conn = connect(migrated_db)
    _memory_file(tmp_path, "-Users-ayush-work-eigen", "late.md", "written without a hook")

    # Nothing called notice(); the gate has to find it itself.
    assert stop_gate.gate(conn, "eigen", root=tmp_path)["n"] == 1


def test_a_long_backlog_is_summarised_not_dumped(migrated_db, tmp_path):
    conn = connect(migrated_db)
    for i in range(9):
        _memory_file(tmp_path, "-Users-ayush-work-eigen", f"m{i}.md", f"fact {i}")

    reason = stop_gate.render_reason(stop_gate.gate(conn, "eigen", root=tmp_path))

    assert "and 4 more" in reason
    assert reason.count(".md  -  ") == stop_gate.MAX_LISTED


def test_the_done_command_never_looks_like_the_whole_list(migrated_db, tmp_path):
    """It spells out two paths. If it stopped there with four files pending,
    an agent copying it would mark two done and silently drop the rest."""
    conn = connect(migrated_db)
    for i in range(4):
        _memory_file(tmp_path, "-Users-ayush-work-eigen", f"m{i}.md", f"fact {i}")

    reason = stop_gate.render_reason(stop_gate.gate(conn, "eigen", root=tmp_path))

    done_line = next(ln for ln in reason.splitlines() if "--done" in ln)
    assert done_line.endswith(" ...")


def _cli_env(migrated_db, monkeypatch, tmp_path, project="eigen"):
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", "ayush")
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", "claude-code")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_PROJECT", project)
    # Without this the CLI sweeps the real ~/.claude/projects and files the
    # developer's own memories into whichever database the test is pointed at.
    monkeypatch.setenv("ECHO_MEMORY_CLAUDE_PROJECTS", str(tmp_path))


def test_the_reconcile_command_runs(migrated_db, monkeypatch, capsys, tmp_path):
    """Both of these shipped broken: the dispatch used a connection the command
    had never opened, and every test called the module functions directly, so
    nothing exercised the path an actual user takes. `echo-memory reconcile`
    raised UnboundLocalError the first time it was run by hand."""
    _cli_env(migrated_db, monkeypatch, tmp_path)

    assert main(["reconcile"]) == 0
    assert "memory file(s)" in capsys.readouterr().out


def test_the_reconcile_command_is_silent_when_quiet(
    migrated_db, monkeypatch, capsys, tmp_path
):
    _cli_env(migrated_db, monkeypatch, tmp_path)

    assert main(["reconcile", "--quiet"]) == 0
    assert capsys.readouterr().out == ""


def test_the_stop_check_command_runs(migrated_db, monkeypatch, capsys, tmp_path):
    _cli_env(migrated_db, monkeypatch, tmp_path)

    assert main(["stop-check", "--hook-json"]) == 0
    # Nothing is queued for this project, so the gate must say nothing at all -
    # a Stop hook that prints on every clean session blocks every session.
    assert capsys.readouterr().out == ""
