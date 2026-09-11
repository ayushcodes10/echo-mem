---
name: "source-command-optimization-parallel-execute"
description: "Migrated source command `optimization-parallel-execute`"
---

# source-command-optimization-parallel-execute

Use this skill when the user asks to run the migrated source command `optimization-parallel-execute`.

## Command Template

# parallel-execute

Execute tasks in parallel for maximum efficiency.

## Usage
```bash
npx Codex-flow optimization parallel-execute [options]
```

## Options
- `--tasks <file>` - Task list file
- `--max-parallel <n>` - Maximum parallel tasks
- `--strategy <type>` - Execution strategy

## Examples
```bash
# Execute task list
npx Codex-flow optimization parallel-execute --tasks tasks.json

# Limit parallelism
npx Codex-flow optimization parallel-execute --tasks tasks.json --max-parallel 5

# Custom strategy
npx Codex-flow optimization parallel-execute --strategy adaptive
```
