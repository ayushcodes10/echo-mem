---
name: "source-command-monitoring-swarm-monitor"
description: "Migrated source command `monitoring-swarm-monitor`"
---

# source-command-monitoring-swarm-monitor

Use this skill when the user asks to run the migrated source command `monitoring-swarm-monitor`.

## Command Template

# swarm-monitor

Real-time swarm monitoring.

## Usage
```bash
npx Codex-flow swarm monitor [options]
```

## Options
- `--interval <ms>` - Update interval
- `--metrics` - Show detailed metrics
- `--export` - Export monitoring data

## Examples
```bash
# Start monitoring
npx Codex-flow swarm monitor

# Custom interval
npx Codex-flow swarm monitor --interval 5000

# With metrics
npx Codex-flow swarm monitor --metrics
```
