"""Every hook has to emit what its own event actually accepts.

`hookSpecificOutput` is not a general-purpose envelope. Claude Code validates
it per event, and rejects it for events that do not define one - PreCompact
among them. The PreCompact hook shipped with

    {"hookSpecificOutput": {"hookEventName": "PreCompact",
                            "additionalContext": "..."}}

copied verbatim from the SessionStart hook next door, where that shape is
correct. It failed on every single compaction with

    PreCompact [...] failed: Hook JSON output validation failed - (root): Invalid input

for its entire life, so the reminder it exists to deliver never reached a
model once. Nothing caught it because no test had ever run a hook script and
looked at what came out; the install test only checked that the scripts were
registered.

PreCompact takes plain stdout instead, which Claude Code passes as
`newCustomInstructions` - the instructions steering the summarisation itself.

SessionStart and UserPromptSubmit do define `hookSpecificOutput`, and both are
observably working, so this pins the distinction rather than banning the shape.
"""

import json
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

# Events whose schema defines hookSpecificOutput. PreCompact, SessionEnd and
# PreToolUse-adjacent events that are absent here reject it outright.
EVENTS_ACCEPTING_HOOK_SPECIFIC_OUTPUT = {
    "PreToolUse",
    "PostToolUse",
    "PostToolBatch",
    "UserPromptSubmit",
    "SessionStart",
    "Stop",
    "SubagentStop",
}

HOOKS = [
    "precompact-hook.sh",
    "session-start-hook.sh",
    "user-prompt-hook.sh",
    "session-stop-hook.sh",
    "capture-memory-hook.sh",
]


def _run(script: str) -> subprocess.CompletedProcess:
    """With no database and no CLI on PATH, which is the state every one of
    these promises to survive."""
    return subprocess.run(
        ["bash", str(SCRIPTS / script)],
        input='{"session_id": "t", "stop_hook_active": false, "trigger": "auto"}',
        capture_output=True, text=True, timeout=30, check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "ECHO_MEMORY_BIN": "/nonexistent"},
    )


@pytest.mark.parametrize("script", HOOKS)
def test_a_hook_never_blocks_the_thing_it_observes(script):
    """Every one of these documents "every path exits 0"."""
    assert _run(script).returncode == 0


@pytest.mark.parametrize("script", HOOKS)
def test_json_output_only_claims_an_event_that_accepts_it(script):
    """The actual bug, stated generally: emitting hookSpecificOutput for an
    event whose schema has no such field."""
    stdout = _run(script).stdout.strip()
    if not stdout:
        return
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return  # plain text, which is what PreCompact wants
    if not isinstance(payload, dict):
        return
    specific = payload.get("hookSpecificOutput")
    if specific is None:
        return
    event = specific.get("hookEventName")
    assert event in EVENTS_ACCEPTING_HOOK_SPECIFIC_OUTPUT, (
        f"{script} emits hookSpecificOutput for {event!r}, which rejects it; "
        "the output will fail validation every time the hook fires"
    )


def test_precompact_emits_plain_text_not_json():
    """Pinned as its own case because the failure was silent: a JSON body here
    is rejected wholesale, and the hook still exits 0, so nothing downstream
    looks wrong."""
    result = _run("precompact-hook.sh")
    stdout = result.stdout.strip()

    assert stdout, "a PreCompact hook with no stdout contributes nothing"
    with pytest.raises(json.JSONDecodeError):
        json.loads(stdout)


def test_precompact_asks_for_the_write_it_exists_to_prompt():
    """Guards against the text drifting into a reminder that names no tool."""
    stdout = _run("precompact-hook.sh").stdout
    assert "write_episode" in stdout
