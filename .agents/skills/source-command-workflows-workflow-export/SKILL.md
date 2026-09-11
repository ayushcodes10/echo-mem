---
name: "source-command-workflows-workflow-export"
description: "Migrated source command `workflows-workflow-export`"
---

# source-command-workflows-workflow-export

Use this skill when the user asks to run the migrated source command `workflows-workflow-export`.

## Command Template

# workflow-export

Export workflows for sharing.

## Usage
```bash
npx Codex-flow workflow export [options]
```

## Options
- `--name <name>` - Workflow to export
- `--format <type>` - Export format
- `--include-history` - Include execution history

## Examples
```bash
# Export workflow
npx Codex-flow workflow export --name "deploy-api"

# As YAML
npx Codex-flow workflow export --name "test-suite" --format yaml

# With history
npx Codex-flow workflow export --name "deploy-api" --include-history
```
