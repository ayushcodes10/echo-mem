#!/usr/bin/env bash
# Remind the agent to record what it learned, immediately before the context
# holding it gets summarised away.
#
# Install as a PreCompact hook (see docs/DEVELOPMENT.md, "Automatic capture").
# Claude Code injects this hook's hookSpecificOutput.additionalContext into the
# model's context, which is the whole reason this works: compaction is the last
# moment the agent still has the full conversation, and the only actor who can
# turn it into entities and facts is the agent itself.
#
# Deliberately does NOT touch the database. A hook on the compaction path is
# latency the user waits through, and a reminder that always fires beats a
# richer one that sometimes hangs on a connection. It also means this keeps
# working when the database is down, which is exactly when you would not want
# compaction to stall.
#
# Never blocks: compaction proceeding is more important than this reminder
# landing, so every path exits 0.

set -u

cat >/dev/null   # drain the PreCompact payload; nothing here needs it

cat <<'JSON'
{
  "hookSpecificOutput": {
    "hookEventName": "PreCompact",
    "additionalContext": "Context is about to be compacted. Anything learned this session that is not already in Echo Memory is about to become unrecoverable. Before continuing, call write_episode for any decision the user stated, correction they made, preference they expressed, or non-obvious thing that cost real time to work out and that you have not already recorded. Skip it only if genuinely nothing new was established. If a recalled fact saved the user from re-explaining something a different tool had told them, record that with record_recall_save now as well."
  }
}
JSON
exit 0
