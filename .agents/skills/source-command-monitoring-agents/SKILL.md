---
name: "source-command-monitoring-agents"
description: "Migrated source command `monitoring-agents`"
---

# source-command-monitoring-agents

Use this skill when the user asks to run the migrated source command `monitoring-agents`.

## Command Template

# List Active Patterns

## 🎯 Key Principle
**This tool coordinates Codex's actions. It does NOT write code or create content.**

## MCP Tool Usage in Codex

**Tool:** `mcp__claude-flow__agent_list`

## Parameters
```json
{
  "swarmId": "current"
}
```

## Description
View all active cognitive patterns and their current focus areas

## Details
Filters:
- **all**: Show all defined patterns
- **active**: Currently engaged patterns
- **idle**: Available but unused patterns
- **busy**: Patterns actively coordinating tasks

## Example Usage

**In Codex:**
1. List all agents: Use tool `mcp__claude-flow__agent_list`
2. Get specific agent metrics: Use tool `mcp__claude-flow__agent_metrics` with parameters `{"agentId": "coder-123"}`
3. Monitor agent performance: Use tool `mcp__claude-flow__swarm_monitor` with parameters `{"interval": 2000}`

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
