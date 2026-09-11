---
name: "source-command-coordination-task-orchestrate"
description: "Migrated source command `coordination-task-orchestrate`"
---

# source-command-coordination-task-orchestrate

Use this skill when the user asks to run the migrated source command `coordination-task-orchestrate`.

## Command Template

# task-orchestrate

Orchestrate complex tasks across the swarm.

## Usage
```bash
npx Codex-flow task orchestrate [options]
```

## Options
- `--task <description>` - Task description
- `--strategy <type>` - Orchestration strategy
- `--priority <level>` - Task priority (low, medium, high, critical)

## Examples
```bash
# Orchestrate development task
npx Codex-flow task orchestrate --task "Implement user authentication"

# High priority task
npx Codex-flow task orchestrate --task "Fix production bug" --priority critical

# With specific strategy
npx Codex-flow task orchestrate --task "Refactor codebase" --strategy parallel
```
