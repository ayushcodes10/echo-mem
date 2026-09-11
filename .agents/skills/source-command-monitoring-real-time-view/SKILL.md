---
name: "source-command-monitoring-real-time-view"
description: "Migrated source command `monitoring-real-time-view`"
---

# source-command-monitoring-real-time-view

Use this skill when the user asks to run the migrated source command `monitoring-real-time-view`.

## Command Template

# real-time-view

Real-time view of swarm activity.

## Usage
```bash
npx Codex-flow monitoring real-time-view [options]
```

## Options
- `--filter <type>` - Filter view
- `--highlight <pattern>` - Highlight pattern
- `--tail <n>` - Show last N events

## Examples
```bash
# Start real-time view
npx Codex-flow monitoring real-time-view

# Filter errors
npx Codex-flow monitoring real-time-view --filter errors

# Highlight pattern
npx Codex-flow monitoring real-time-view --highlight "API"
```
