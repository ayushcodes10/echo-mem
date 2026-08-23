#!/usr/bin/env bash
# Queue a Claude Code memory file for ingestion into Echo Memory.
#
# Install as a PostToolUse hook on Write|Edit (see docs/DEVELOPMENT.md,
# "Automatic capture"). Claude Code passes the tool call as JSON on stdin; the
# only field this needs is the path that was written.
#
# Why a hook rather than trusting the agent to call write_episode: over the
# first two days of the v1a trial write_episode fired 4 times by model
# discretion while the file-based memory wrote 7 files by hook. Capture that
# depends on remembering to capture is the thing being fixed.
#
# This queues; it does not extract. Turning prose into entities and facts needs
# a model, and the server deliberately never calls one (design doc, MCP tool
# contract, architecture pivot). `query_memory` surfaces the queue at session
# start so the agent that can do the extraction is told there is work.
#
# Never blocks or fails a tool call: a memory-capture side effect has no
# business breaking the edit that triggered it. Every path exits 0.

set -u

: "${ECHO_MEMORY_BIN:=echo-memory}"

payload=$(cat)

# Prefer jq; fall back to a narrow grep so the hook still works without it.
if command -v jq >/dev/null 2>&1; then
  file_path=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
else
  file_path=$(printf '%s' "$payload" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
fi

[ -n "${file_path:-}" ] || exit 0

# Only Claude Code's own memory files. Anything else written during a session
# is source code, scratch output or config, none of which is a memory.
case "$file_path" in
  */.claude/projects/*/memory/*.md) ;;
  *) exit 0 ;;
esac

# MEMORY.md is the index, not a memory: its content is one line per real
# memory file, each of which triggers this hook on its own.
case "$(basename "$file_path")" in
  MEMORY.md) exit 0 ;;
esac

[ -f "$file_path" ] || exit 0

"$ECHO_MEMORY_BIN" notice "$file_path" >/dev/null 2>&1 || true
exit 0
