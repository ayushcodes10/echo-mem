---
name: "source-command-swarm-swarm"
description: "Migrated source command `swarm-swarm`"
---

# source-command-swarm-swarm

Use this skill when the user asks to run the migrated source command `swarm-swarm`.

## Command Template

# swarm

Main swarm orchestration command for Codex Flow.

## Usage
```bash
npx Codex-flow swarm <objective> [options]
```

## Options
- `--strategy <type>` - Execution strategy (research, development, analysis, testing)
- `--mode <type>` - Coordination mode (centralized, distributed, hierarchical, mesh)
- `--max-agents <n>` - Maximum number of agents (default: 5)
- `--Codex` - Open Codex CLI with swarm prompt
- `--parallel` - Enable parallel execution

## Examples
```bash
# Basic swarm
npx Codex-flow swarm "Build REST API"

# With strategy
npx Codex-flow swarm "Research AI patterns" --strategy research

# Open in Codex
npx Codex-flow swarm "Build API" --Codex
```
