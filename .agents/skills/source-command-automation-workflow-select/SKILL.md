---
name: "source-command-automation-workflow-select"
description: "Migrated source command `automation-workflow-select`"
---

# source-command-automation-workflow-select

Use this skill when the user asks to run the migrated source command `automation-workflow-select`.

## Command Template

# workflow-select

Automatically select optimal workflow based on task type.

## Usage
```bash
npx Codex-flow automation workflow-select [options]
```

## Options
- `--task <description>` - Task description
- `--constraints <list>` - Workflow constraints
- `--preview` - Preview without executing

## Examples
```bash
# Select workflow for task
npx Codex-flow automation workflow-select --task "Deploy to production"

# With constraints
npx Codex-flow automation workflow-select --constraints "no-downtime,rollback"

# Preview mode
npx Codex-flow automation workflow-select --task "Database migration" --preview
```
