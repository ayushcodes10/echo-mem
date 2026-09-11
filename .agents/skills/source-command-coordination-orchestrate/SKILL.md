---
name: "source-command-coordination-orchestrate"
description: "Migrated source command `coordination-orchestrate`"
---

# source-command-coordination-orchestrate

Use this skill when the user asks to run the migrated source command `coordination-orchestrate`.

## Command Template

# Coordinate Task Execution

## 🎯 Key Principle
**This tool coordinates Codex's actions. It does NOT write code or create content.**

## MCP Tool Usage in Codex

**Tool:** `mcp__claude-flow__task_orchestrate`

## Parameters
```json
{"task": "Implement authentication system", "strategy": "parallel", "priority": "high"}
```

## Description
Break down and coordinate complex tasks for systematic execution by Codex

## Details
Orchestration strategies:
- **parallel**: Codex works on independent components simultaneously
- **sequential**: Step-by-step execution for dependent tasks
- **adaptive**: Dynamically adjusts based on task complexity

The orchestrator creates a plan that Codex follows using its native tools.

## Example Usage

**In Codex:**
1. Use the tool: `mcp__claude-flow__task_orchestrate`
2. With parameters: `{"task": "Implement authentication system", "strategy": "parallel", "priority": "high"}`
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
