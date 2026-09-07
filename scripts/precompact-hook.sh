#!/usr/bin/env bash
# Remind the agent to record what it learned, immediately before the context
# holding it gets summarised away.
#
# Install as a PreCompact hook (see docs/DEVELOPMENT.md, "Automatic capture").
#
# THE OUTPUT IS PLAIN TEXT ON STDOUT, NOT JSON. This is not a style choice.
# `hookSpecificOutput.additionalContext` is the mechanism the SessionStart and
# UserPromptSubmit hooks in this directory use, and it is NOT valid for
# PreCompact: Claude Code's hook schema accepts `hookSpecificOutput` only for
# PreToolUse, UserPromptSubmit, PostToolUse, PostToolBatch and Stop/SubagentStop.
# Emitting it here failed validation on every single compaction with
#
#     PreCompact [...] failed: Hook JSON output validation failed - (root): Invalid input
#
# so from the day it was written until 2026-09-07 this reminder never once
# reached a model. Copying the shape of the hook next door is what hid it.
#
# What stdout actually does here is better than what the JSON was reaching for.
# Claude Code collects each successful PreCompact hook's stdout and passes it as
# `newCustomInstructions` - the instructions steering the summarisation itself -
# rather than as one more message that the summariser is free to drop.
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

cat <<'TEXT'
Anything learned this session that is not already in Echo Memory is about to become unrecoverable. Before summarising, call write_episode for any decision the user stated, correction they made, preference they expressed, or non-obvious thing that cost real time to work out and that is not already recorded. Skip it only if genuinely nothing new was established. If a recalled fact saved the user from re-explaining something a different tool had told them, record that with record_recall_save as well. Preserve any such unrecorded finding verbatim in the summary so the next context can still write it.
TEXT
exit 0
