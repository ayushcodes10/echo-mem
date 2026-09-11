---
name: "source-command-workflows-workflow-execute"
description: "Migrated source command `workflows-workflow-execute`"
---

# source-command-workflows-workflow-execute

Use this skill when the user asks to run the migrated source command `workflows-workflow-execute`.

## Command Template

# workflow-execute

Execute saved workflows.

## Usage
```bash
npx Codex-flow workflow execute [options]
```

## Options
- `--name <name>` - Workflow name
- `--params <json>` - Workflow parameters
- `--dry-run` - Preview execution

## Examples
```bash
# Execute workflow
npx Codex-flow workflow execute --name "deploy-api"

# With parameters
npx Codex-flow workflow execute --name "test-suite" --params '{"env": "staging"}'

# Dry run
npx Codex-flow workflow execute --name "deploy-api" --dry-run
```
