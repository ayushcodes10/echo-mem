"""Registering the capture hooks.

DEVELOPMENT.md used to document four hooks as four JSON blocks to merge by
hand. The failure that shape produces is not a crash: it is a machine that
looks configured and has one hook missing, which is indistinguishable from a
working install until months of memory have quietly not been captured. These
tests pin the properties that make one command safe to re-run instead."""

import json

import pytest

from echo_memory.cli import hooks
from echo_memory.infra.config import Config

SCRIPTS = "/opt/echo-mem/scripts"
BIN = "/opt/echo-mem/.venv/bin/echo-memory"


@pytest.fixture
def config():
    return Config(
        user_id="ayush",
        agent_id="claude-code",
        database_url="postgresql://postgres:postgres@localhost:5433/echo_memory",
    )


def _plan(config):
    from pathlib import Path

    return hooks.plan(config, Path(SCRIPTS), BIN)


def test_every_hook_in_the_set_is_registered(config):
    events = {item["event"] for item in _plan(config)}
    # The set is the mechanism. A missing member is the failure mode this
    # command exists to remove, so the test names them rather than counting.
    assert events == {
        "PostToolUse", "SessionStart", "UserPromptSubmit", "PreCompact", "Stop"
    }


def test_the_write_matcher_is_scoped_to_file_writes(config):
    entry = next(i["entry"] for i in _plan(config) if i["event"] == "PostToolUse")
    assert entry["matcher"] == "Write|Edit"


def test_credentials_are_inlined_because_a_gui_client_has_no_shell(config):
    command = _plan(config)[0]["entry"]["hooks"][0]["command"]
    assert "ECHO_MEMORY_USER_ID=ayush" in command
    assert "ECHO_MEMORY_AGENT_ID=claude-code" in command
    assert command.endswith("capture-memory-hook.sh")


def test_a_credential_file_is_preferred_over_an_inlined_url(config, monkeypatch):
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL_FILE", "/run/secrets/echo")
    command = _plan(config)[0]["entry"]["hooks"][0]["command"]
    assert "ECHO_MEMORY_DATABASE_URL_FILE=/run/secrets/echo" in command
    assert "ECHO_MEMORY_DATABASE_URL=" not in command


def test_rerunning_replaces_our_hooks_instead_of_stacking_them(config):
    entries = _plan(config)
    once = hooks.merge({}, entries)
    twice = hooks.merge(once, entries)
    assert len(twice["hooks"]["SessionStart"]) == 1
    assert once == twice


def test_hooks_someone_else_registered_survive(config):
    theirs = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "/other/tool"}]}],
            "Notification": [{"hooks": [{"type": "command", "command": "/beep"}]}],
        }
    }
    merged = hooks.merge(theirs, _plan(config))
    stop_commands = [
        h["command"] for entry in merged["hooks"]["Stop"] for h in entry["hooks"]
    ]
    assert "/other/tool" in stop_commands
    # An event we do not touch at all must come through untouched.
    assert merged["hooks"]["Notification"] == theirs["hooks"]["Notification"]


def test_writing_lands_on_disk_and_can_be_read_back(config, tmp_path):
    settings = tmp_path / "settings.json"
    hooks.apply(config, __import__("pathlib").Path(SCRIPTS), BIN, settings)
    written = json.loads(settings.read_text())
    assert set(written["hooks"]) >= {"Stop", "SessionStart"}


def test_an_unparseable_settings_file_is_refused_not_overwritten(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{ this is not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        hooks.read_settings(settings)
    # The point of refusing: their file is still there.
    assert settings.read_text() == "{ this is not json"


def test_hand_merged_hooks_from_the_old_docs_are_upgraded_not_doubled(config):
    """Every machine installed before this command existed got its hooks by
    hand-merging the JSON blocks the docs printed, so they carry no marker.
    Matching only the marker would leave those in place and add a second copy
    of each - every hook firing twice, every memory file noticed twice."""
    handwritten = {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                "ECHO_MEMORY_USER_ID=ayush "
                                "/old/path/echo-mem/scripts/session-start-hook.sh"
                            ),
                        }
                    ]
                }
            ]
        }
    }
    merged = hooks.merge(handwritten, _plan(config))
    assert len(merged["hooks"]["SessionStart"]) == 1
    assert SCRIPTS in merged["hooks"]["SessionStart"][0]["hooks"][0]["command"]


def test_a_foreign_stop_hook_is_not_mistaken_for_ours(config):
    theirs = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "/gstack/hooks/timeline-stop-hook"}]}
            ]
        }
    }
    merged = hooks.merge(theirs, _plan(config))
    assert len(merged["hooks"]["Stop"]) == 2
