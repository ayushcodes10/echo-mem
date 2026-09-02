#!/usr/bin/env bash
# Hold a session open until the memory files it wrote are in the graph.
#
# Install as a Stop hook (see docs/DEVELOPMENT.md, "Automatic capture").
#
# Why this exists: from 2026-08-23 to 2026-09-02 the session-start briefing
# asked every session in every project to drain the capture queue. 16 memory
# files were written across eigen and dugout in that window and none were
# turned into facts by the session that wrote them. Asking does not work;
# the hooks in this directory are the only things in the system that do.
#
# Fires at most once per session. Claude Code sets stop_hook_active when the
# session is already continuing because of a stop hook, and honouring that is
# what keeps a nudge from becoming a loop the user has to kill.
#
# Never blocks on failure: if the database is down or slow the session ends
# normally. A hook that can strand a session is worse than a missed memory.

set -u

: "${ECHO_MEMORY_BIN:=echo-memory}"
: "${ECHO_MEMORY_STOP_TIMEOUT:=10}"

payload=$(cat)

if command -v jq >/dev/null 2>&1; then
  active=$(printf '%s' "$payload" | jq -r '.stop_hook_active // false' 2>/dev/null)
else
  active=$(printf '%s' "$payload" | grep -o '"stop_hook_active"[[:space:]]*:[[:space:]]*true' | head -1)
  [ -n "$active" ] && active="true" || active="false"
fi

# Already continuing from a previous stop-hook block: say nothing, let it end.
[ "$active" = "true" ] && exit 0

if command -v timeout >/dev/null 2>&1; then
  out=$(timeout "$ECHO_MEMORY_STOP_TIMEOUT" "$ECHO_MEMORY_BIN" stop-check --hook-json 2>/dev/null)
else
  out=$("$ECHO_MEMORY_BIN" stop-check --hook-json 2>/dev/null)
fi

[ -n "${out:-}" ] && printf '%s\n' "$out"
exit 0
