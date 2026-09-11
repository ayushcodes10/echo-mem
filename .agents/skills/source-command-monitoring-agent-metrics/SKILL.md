---
name: "source-command-monitoring-agent-metrics"
description: "Migrated source command `monitoring-agent-metrics`"
---

# source-command-monitoring-agent-metrics

Use this skill when the user asks to run the migrated source command `monitoring-agent-metrics`.

## Command Template

# agent-metrics

View agent performance metrics.

## Usage
```bash
npx Codex-flow agent metrics [options]
```

## Options
- `--agent-id <id>` - Specific agent
- `--period <time>` - Time period
- `--format <type>` - Output format

## Examples
```bash
# All agents metrics
npx Codex-flow agent metrics

# Specific agent
npx Codex-flow agent metrics --agent-id agent-001

# Last hour
npx Codex-flow agent metrics --period 1h
```
