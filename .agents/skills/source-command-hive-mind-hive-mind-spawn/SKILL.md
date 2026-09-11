---
name: "source-command-hive-mind-hive-mind-spawn"
description: "Migrated source command `hive-mind-hive-mind-spawn`"
---

# source-command-hive-mind-hive-mind-spawn

Use this skill when the user asks to run the migrated source command `hive-mind-hive-mind-spawn`.

## Command Template

# hive-mind-spawn

Spawn a Hive Mind swarm with queen-led coordination.

## Usage
```bash
npx Codex-flow hive-mind spawn <objective> [options]
```

## Options
- `--queen-type <type>` - Queen type (strategic, tactical, adaptive)
- `--max-workers <n>` - Maximum worker agents
- `--consensus <type>` - Consensus algorithm
- `--Codex` - Generate Codex spawn commands

## Examples
```bash
npx Codex-flow hive-mind spawn "Build API"
npx Codex-flow hive-mind spawn "Research patterns" --queen-type adaptive
npx Codex-flow hive-mind spawn "Build service" --Codex
```
