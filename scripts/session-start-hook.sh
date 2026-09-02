#!/usr/bin/env bash
# Tell a starting session that Echo Memory exists, what it already knows about
# this project, and what is queued.
#
# Install as a SessionStart hook (see docs/DEVELOPMENT.md, "Automatic capture").
# Claude Code injects hookSpecificOutput.additionalContext deterministically,
# which is the whole point: instructions in a file can be skimmed past, and the
# previous nudge lived inside query_memory's response, so an agent only learned
# memory existed if it had already used memory. Zero organic writes in two days
# is what that circle looks like from the outside.
#
# Session start is latency the user waits through before typing, so this is
# time-boxed. If the database is slow or down, the session starts without a
# briefing rather than starting late; a missing briefing costs one session's
# recall, a hung hook costs the session.
#
# Never blocks: every path exits 0.

set -u

: "${ECHO_MEMORY_BIN:=echo-memory}"
: "${ECHO_MEMORY_BRIEF_TIMEOUT:=5}"

cat >/dev/null   # drain the SessionStart payload

# Heal any drift before briefing: a memory file edited while the capture hook
# was not installed, or through a path it did not match, is invisible to the
# queue until something reads the filesystem. Three eigen files sat in that
# state until 2026-09-02. Silent and best-effort - the briefing matters more
# than the sweep, and the sweep must never be what makes a session start late.
if command -v timeout >/dev/null 2>&1; then
  timeout "$ECHO_MEMORY_BRIEF_TIMEOUT" "$ECHO_MEMORY_BIN" reconcile --quiet >/dev/null 2>&1 || true
else
  "$ECHO_MEMORY_BIN" reconcile --quiet >/dev/null 2>&1 || true
fi

# The project is resolved from the hook's own working directory, which Claude
# Code sets to the project root - the same rule the MCP server uses, so a fact
# written this session and the briefing that mentioned it agree on the name.
if command -v timeout >/dev/null 2>&1; then
  brief=$(timeout "$ECHO_MEMORY_BRIEF_TIMEOUT" "$ECHO_MEMORY_BIN" session-brief --hook-json 2>/dev/null)
else
  brief=$("$ECHO_MEMORY_BIN" session-brief --hook-json 2>/dev/null)
fi

[ -n "${brief:-}" ] && printf '%s\n' "$brief"
exit 0
