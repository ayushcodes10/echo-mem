---
name: "source-command-coordination-spawn"
description: "Migrated source command `coordination-spawn`"
---

# source-command-coordination-spawn

Use this skill when the user asks to run the migrated source command `coordination-spawn`.

## Command Template

# Create Cognitive Patterns

## 🎯 Key Principle
**This tool coordinates Codex's actions. It does NOT write code or create content.**

## MCP Tool Usage in Codex

**Tool:** `mcp__claude-flow__agent_spawn`

## Parameters
```json
{"type": "researcher", "name": "Literature Analysis", "capabilities": ["deep-analysis"]}
```

## Description
Define cognitive patterns that represent different approaches Codex can take

## Details
Agent types represent thinking patterns, not actual coders:
- **researcher**: Systematic exploration approach
- **coder**: Implementation-focused thinking
- **analyst**: Data-driven decision making
- **architect**: Big-picture system design
- **reviewer**: Quality and consistency checking

These patterns guide how Codex approaches different aspects of your task.

## Example Usage

**In Codex:**
1. Use the tool: `mcp__claude-flow__agent_spawn`
2. With parameters: `{"type": "researcher", "name": "Literature Analysis", "capabilities": ["deep-analysis"]}`
3. Codex then executes the coordinated plan using its native tools

## Important Reminders
- ✅ This tool provides coordination and structure
- ✅ Codex performs all actual implementation
- ❌ The tool does NOT write code
- ❌ The tool does NOT access files directly
- ❌ The tool does NOT execute commands

## See Also
- Main documentation: /AGENTS.md
- Other commands in this category
- Workflow examples in /workflows/
