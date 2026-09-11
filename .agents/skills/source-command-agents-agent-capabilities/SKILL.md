---
name: "source-command-agents-agent-capabilities"
description: "Migrated source command `agents-agent-capabilities`"
---

# source-command-agents-agent-capabilities

Use this skill when the user asks to run the migrated source command `agents-agent-capabilities`.

## Command Template

# agent-capabilities

Matrix of agent capabilities and their specializations.

## Capability Matrix

| Agent Type | Primary Skills | Best For |
|------------|---------------|----------|
| coder | Implementation, debugging | Feature development |
| researcher | Analysis, synthesis | Requirements gathering |
| tester | Testing, validation | Quality assurance |
| architect | Design, planning | System architecture |

## Querying Capabilities
```bash
# List all capabilities
npx Codex-flow agents capabilities

# For specific agent
npx Codex-flow agents capabilities --type coder
```
