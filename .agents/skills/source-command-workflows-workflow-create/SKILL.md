---
name: "source-command-workflows-workflow-create"
description: "Migrated source command `workflows-workflow-create`"
---

# source-command-workflows-workflow-create

Use this skill when the user asks to run the migrated source command `workflows-workflow-create`.

## Command Template

# workflow-create

Create reusable workflow templates.

## Usage
```bash
npx Codex-flow workflow create [options]
```

## Options
- `--name <name>` - Workflow name
- `--from-history` - Create from history
- `--interactive` - Interactive creation

## Examples
```bash
# Create workflow
npx Codex-flow workflow create --name "deploy-api"

# From history
npx Codex-flow workflow create --name "test-suite" --from-history

# Interactive mode
npx Codex-flow workflow create --interactive
```
