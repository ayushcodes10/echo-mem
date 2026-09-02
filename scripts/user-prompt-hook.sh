#!/usr/bin/env bash
# Retrieve memory against the prompt the user just typed, and inject it before
# the agent acts.
#
# Install as a UserPromptSubmit hook (see docs/DEVELOPMENT.md). This is the only
# surface that makes recall happen rather than asking an agent to remember to
# ask for it. On 2026-08-25 a dugout session received the session-start briefing
# in context, then made 31 tool calls without a single memory call - the
# plumbing was fine, remembering was the problem.
#
# Retrieval is lexical-only. The hook runs in a fresh process on every prompt
# and the embedding model costs 6.2 seconds of cold start, which is not a
# latency anyone should pay per prompt. Postgres full-text search needs no
# model. Recall is worse than a full query_memory call and that is the right
# trade: some relevant memory on every prompt beats better memory when somebody
# remembers to ask.
#
# Silent when nothing matches. This injects into every prompt, and a hook that
# always speaks becomes noise the model learns to skim.
#
# Never blocks the prompt: a timeout discards this output and the prompt still
# reaches Claude, and every path here exits 0 regardless.

set -u

: "${ECHO_MEMORY_BIN:=echo-memory}"
: "${ECHO_MEMORY_RECALL_TIMEOUT:=5}"

payload=$(cat)

if command -v jq >/dev/null 2>&1; then
  prompt=$(printf '%s' "$payload" | jq -r '.prompt // empty' 2>/dev/null)
  session_id=$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)
else
  prompt=$(printf '%s' "$payload" | sed -n 's/.*"prompt"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p' | head -1)
  session_id=$(printf '%s' "$payload" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
fi

[ -n "${prompt:-}" ] || exit 0

# Attribution is best-effort: an older CLI rejects the flag, and a recorded
# read matters more than a labelled one.
sid_args=""
[ -n "${session_id:-}" ] && sid_args="--session-id $session_id"

if command -v timeout >/dev/null 2>&1; then
  out=$(printf '%s' "$prompt" | timeout "$ECHO_MEMORY_RECALL_TIMEOUT" "$ECHO_MEMORY_BIN" recall --hook-json $sid_args 2>/dev/null)
else
  out=$(printf '%s' "$prompt" | "$ECHO_MEMORY_BIN" recall --hook-json $sid_args 2>/dev/null)
fi

[ -n "${out:-}" ] && printf '%s\n' "$out"
exit 0
