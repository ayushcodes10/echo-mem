---
name: "source-command-coordination-init"
description: "Migrated source command `coordination-init`"
---

# source-command-coordination-init

Use this skill when the user asks to run the migrated source command `coordination-init`.

## Command Template

# Initialize Coordination Framework

## 🎯 Key Principle
**This tool coordinates Codex's actions. It does NOT write code or create content.**

## MCP Tool Usage in Codex

**Tool:** `mcp__claude-flow__swarm_init`

## Parameters
```json
{"topology": "mesh", "maxAgents": 5, "strategy": "balanced"}
```

## Description
Set up a coordination topology to guide Codex's approach to complex tasks

## Details
This tool creates a coordination framework that helps Codex:
- Break down complex problems systematically
- Approach tasks from multiple perspectives
- Maintain consistency across large projects
- Work more efficiently through structured coordination

Remember: This does NOT create actual coding agents. It creates a coordination pattern for Codex to follow.

## Example Usage

**In Codex:**
1. Use the tool: `mcp__claude-flow__swarm_init`
2. With parameters: `{"topology": "mesh", "maxAgents": 5, "strategy": "balanced"}`
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
