"""The filesystem sweep that heals a missed capture hook.

Three eigen memory files were found on 2026-09-02 holding content the queue had
never seen: the capture hook was not installed when they were written, or the
edit came through a path it did not match. Nothing detected that, because a
queue only knows what it was told. These tests cover the scan half, which is
where the scope has to match the hook's exactly - if the two disagreed the
sweep would either keep reopening files the hook ignores or keep missing files
the hook queues."""

from echo_memory.cli import reconcile


def _memory_file(root, encoded_project, name, text="a fact"):
    d = root / encoded_project / "memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return d / name


def test_finds_memory_files_across_every_project(tmp_path):
    _memory_file(tmp_path, "-Users-ayush-work-eigen", "pause.md")
    _memory_file(tmp_path, "-Users-ayush-work-dugout", "hosts.md")
    found = reconcile.memory_files(tmp_path)
    assert {f.name for f, _ in found} == {"pause.md", "hosts.md"}


def test_the_index_is_not_a_memory(tmp_path):
    _memory_file(tmp_path, "-Users-ayush-work-eigen", "MEMORY.md")
    _memory_file(tmp_path, "-Users-ayush-work-eigen", "real.md")
    # MEMORY.md lists the real memories one line each, and every one of those
    # is scanned on its own. Ingesting it would add a fact per pointer.
    assert [f.name for f, _ in reconcile.memory_files(tmp_path)] == ["real.md"]


def test_a_project_directory_without_memories_is_skipped(tmp_path):
    (tmp_path / "-Users-ayush-work-empty").mkdir(parents=True)
    assert reconcile.memory_files(tmp_path) == []


def test_a_missing_projects_directory_is_not_an_error(tmp_path):
    assert reconcile.memory_files(tmp_path / "nope") == []


def test_files_are_attributed_to_their_own_project_not_the_cwd(tmp_path):
    _memory_file(tmp_path, "-Users-ayush-work-eigen", "pause.md")
    (_, project), = reconcile.memory_files(tmp_path)
    # The encoded directory names the project the memory belongs to. Falling
    # back to the sweeping process's cwd would file every project's memories
    # under whichever repo happened to run the sweep.
    assert project == "eigen"


def test_render_stays_silent_shaped_when_nothing_drifted():
    out = reconcile.render({"scanned": 24, "new": [], "changed": [], "unchanged": 24})
    assert "Nothing drifted" in out and "24" in out


def test_render_separates_never_seen_from_changed():
    out = reconcile.render({
        "scanned": 3,
        "new": [{"path": "/m/a.md", "project": "eigen"}],
        "changed": [{"path": "/m/b.md", "project": "dugout"}],
        "unchanged": 1,
    })
    assert "a.md" in out and "never noticed" in out
    assert "b.md" in out and "changed since ingest" in out


def test_the_projects_root_can_be_pointed_elsewhere(tmp_path, monkeypatch):
    """Resolved per call, not at import. A test that swept the real
    ~/.claude/projects filed the developer's own memories into the test
    database the first time `echo-memory stop-check` ran through the CLI."""
    monkeypatch.setenv(reconcile.ROOT_ENV, str(tmp_path))
    assert reconcile.claude_projects_root() == tmp_path


def test_without_an_override_it_is_the_real_location(monkeypatch):
    monkeypatch.delenv(reconcile.ROOT_ENV, raising=False)
    assert reconcile.claude_projects_root() == reconcile.DEFAULT_CLAUDE_PROJECTS
