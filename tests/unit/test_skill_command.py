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
