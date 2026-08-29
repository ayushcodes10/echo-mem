"""Instructions for a client that has nowhere to install them.

Claude Desktop was correctly registered, with its own agent id, and its MCP log
showed six connections, three tools/list calls and zero tools/call - ever. The
tools were there; nothing told the model to reach for them. It has no hooks, no
rules file and no per-project config on disk, so the only durable channel is a
Project's custom instructions, typed by a human."""

from echo_memory.cli.skill import render_skill


def test_it_prints_the_same_text_the_other_clients_get():
    from echo_memory.cli.install import skill_text

    assert skill_text().strip() in render_skill("generic")


def test_the_default_explains_where_to_paste_it():
    text = render_skill()

    assert "custom instructions" in text
    assert "paste from here" in text and "to here" in text


def test_it_says_how_to_check_it_worked():
    """Wiring without a way to confirm it is the failure this whole command
    exists to fix."""
    text = render_skill()

    assert "echo-memory status" in text
    assert "claude-desktop" in text


def test_generic_is_the_bare_text_with_no_paste_furniture():
    assert not render_skill("generic").startswith("Paste")


def test_package_writes_an_uploadable_archive(tmp_path):
    """Claude Desktop takes a skill as a zip containing a directory with
    SKILL.md at its root."""
    import zipfile

    from echo_memory.cli.install import skill_text
    from echo_memory.cli.skill import package

    written = package(tmp_path)

    assert written.name == "echo-memory-skill.zip"
    with zipfile.ZipFile(written) as archive:
        assert archive.namelist() == ["echo-memory/SKILL.md"]
        assert archive.read("echo-memory/SKILL.md").decode() == skill_text()


def test_package_accepts_an_explicit_filename(tmp_path):
    from echo_memory.cli.skill import package

    assert package(tmp_path / "sub" / "mine.zip").name == "mine.zip"


def test_the_packaged_skill_carries_the_frontmatter_a_skill_needs(tmp_path):
    """Without name and description in the frontmatter, an uploaded skill has
    nothing to match against and is never surfaced."""
    import zipfile

    from echo_memory.cli.skill import package

    with zipfile.ZipFile(package(tmp_path)) as archive:
        text = archive.read("echo-memory/SKILL.md").decode()
    assert text.startswith("---\nname: echo-memory\n")
    assert "description:" in text.split("---")[1]
