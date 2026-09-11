---
name: "source-command-coordination-agent-spawn"
description: "Migrated source command `coordination-agent-spawn`"
---

# source-command-coordination-agent-spawn

Use this skill when the user asks to run the migrated source command `coordination-agent-spawn`.

## Command Template

# agent-spawn

Spawn a new agent in the current swarm.

## Usage
```bash
npx Codex-flow agent spawn [options]
```

## Options
- `--type <type>` - Agent type (coder, researcher, analyst, tester, coordinator)
- `--name <name>` - Custom agent name
- `--skills <list>` - Specific skills (comma-separated)

## Examples
```bash
# Spawn coder agent
npx Codex-flow agent spawn --type coder

# With custom name
npx Codex-flow agent spawn --type researcher --name "API Expert"

# With specific skills
npx Codex-flow agent spawn --type coder --skills "python,fastapi,testing"
```
