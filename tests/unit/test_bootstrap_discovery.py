"""First-run discovery against a synthetic home directory: which references
get found, and which project each document is attributed to."""

from echo_memory.infra.project import decode_claude_project_dir
from echo_memory.ingestion import bootstrap


def _home(tmp_path, work_dirs=("eigen", "dugout")):
    """A home laid out like a real one: project directories plus the reference
    stores that point at them."""
    home = tmp_path / "home"
    work = tmp_path / "work"
    for name in work_dirs:
        (work / name).mkdir(parents=True)

    for name in work_dirs:
        encoded = str(work / name).replace("/", "-")
        memory = home / ".claude" / "projects" / encoded / "memory"
        memory.mkdir(parents=True)
        (memory / f"{name}-note.md").write_text(f"a real memory about {name}")
        (memory / "MEMORY.md").write_text(f"- [note]({name}-note.md)")

        digest = home / ".claude" / "company-memory" / "projects"
        digest.mkdir(parents=True, exist_ok=True)
        (digest / f"{encoded}.md").write_text(
            f"# {encoded}\n\nPath: {work / name}\n\nLast active: 2026-08-23\n"
        )
    return home, work


def test_finds_hand_written_memories(tmp_path):
    home, _ = _home(tmp_path)

    found = bootstrap.discover(home)

    memories = [f for f in found if f["source"] == bootstrap.CLAUDE_MEMORY]
    assert {f["path"].name for f in memories} == {"eigen-note.md", "dugout-note.md"}


def test_skips_the_memory_index(tmp_path):
    """MEMORY.md is a table of contents whose every line points at a file that
    is itself discovered."""
    home, _ = _home(tmp_path)

    found = bootstrap.discover(home)

    assert not any(f["path"].name == "MEMORY.md" for f in found)


def test_project_instructions_are_found_in_the_project_itself(tmp_path):
    home, work = _home(tmp_path)
    (work / "eigen" / "CLAUDE.md").write_text("# eigen instructions")

    found = bootstrap.discover(home)

    instructions = [f for f in found if f["source"] == bootstrap.PROJECT_INSTRUCTIONS]
    assert len(instructions) == 1
    assert instructions[0]["project"] == "eigen"


def test_gstack_learnings_reconcile_against_known_projects(tmp_path):
    """gstack directories are sometimes <owner>-<repo>; splitting on dashes
    can't recover a repo name that contains one."""
    home, _ = _home(tmp_path, work_dirs=("ayush-trade-bot",))
    learnings = home / ".gstack" / "projects" / "ayushcodes10-ayush-trade-bot"
    learnings.mkdir(parents=True)
    (learnings / "learnings.jsonl").write_text('{"insight": "something learned"}\n')

    found = bootstrap.discover(home)

    gstack = [f for f in found if f["source"] == bootstrap.GSTACK_LEARNINGS]
    assert gstack[0]["project"] == "ayush-trade-bot"


def test_unknown_gstack_project_keeps_its_own_name(tmp_path):
    home, _ = _home(tmp_path)
    learnings = home / ".gstack" / "projects" / "some-other-thing"
    learnings.mkdir(parents=True)
    (learnings / "learnings.jsonl").write_text("{}\n")

    found = bootstrap.discover(home)

    gstack = [f for f in found if f["source"] == bootstrap.GSTACK_LEARNINGS]
    assert gstack[0]["project"] == "some-other-thing"


def test_company_memory_digests_are_no_longer_swept(tmp_path):
    """The company-memory tool was uninstalled; its digests were derivative of
    the per-project memory files that are still swept."""
    home, _ = _home(tmp_path)

    found = bootstrap.discover(home)

    assert not any("company-memory" in str(f["path"]) for f in found)
    assert "company-memory" not in bootstrap.SOURCES


def test_sources_can_be_limited(tmp_path):
    home, _ = _home(tmp_path)

    found = bootstrap.discover(home, sources=(bootstrap.CLAUDE_MEMORY,))

    assert {f["source"] for f in found} == {bootstrap.CLAUDE_MEMORY}


def test_hand_written_notes_are_ordered_before_other_sources(tmp_path):
    home, work = _home(tmp_path)
    (work / "eigen" / "CLAUDE.md").write_text("# eigen instructions")

    found = bootstrap.discover(home)

    first_other = next(
        i for i, f in enumerate(found) if f["source"] != bootstrap.CLAUDE_MEMORY
    )
    last_memory = max(i for i, f in enumerate(found) if f["source"] == bootstrap.CLAUDE_MEMORY)
    assert last_memory < first_other


def test_a_path_reachable_two_ways_is_queued_once(tmp_path):
    home, work = _home(tmp_path, work_dirs=("eigen",))
    # CLAUDE.md reachable via both the encoded project dir and the digest's Path line
    (work / "eigen" / "CLAUDE.md").write_text("# instructions")

    found = bootstrap.discover(home)

    paths = [str(f["path"]) for f in found]
    assert len(paths) == len(set(paths))


def test_transcripts_are_never_swept(tmp_path):
    """Raw session transcripts are enormous and mostly tool output; their
    signal is already distilled into the memory files that are swept."""
    home, _ = _home(tmp_path)
    encoded = next((home / ".claude" / "projects").iterdir())
    (encoded / "a-session.jsonl").write_text('{"type": "user"}\n')

    found = bootstrap.discover(home)

    assert not any(f["path"].suffix == ".jsonl" and "projects" in str(f["path"]) for f in found)


def test_empty_home_finds_nothing_rather_than_failing(tmp_path):
    assert bootstrap.discover(tmp_path / "empty-home") == []


def test_decoder_prefers_a_directory_that_actually_exists(tmp_path):
    nested = tmp_path / "work" / "yallahaji" / "Backend"
    nested.mkdir(parents=True)
    encoded = str(nested).replace("/", "-")

    assert decode_claude_project_dir(encoded) == "Backend"


def test_decoder_keeps_dashes_that_belong_to_the_name(tmp_path):
    hyphenated = tmp_path / "work" / "ayush-trade-bot"
    hyphenated.mkdir(parents=True)
    encoded = str(hyphenated).replace("/", "-")

    assert decode_claude_project_dir(encoded) == "ayush-trade-bot"


def test_parse_learnings_skips_malformed_lines(tmp_path):
    path = tmp_path / "learnings.jsonl"
    path.write_text('{"insight": "one"}\nnot json\n\n{"insight": "two"}\n')

    assert [r["insight"] for r in bootstrap.parse_learnings(path)] == ["one", "two"]
