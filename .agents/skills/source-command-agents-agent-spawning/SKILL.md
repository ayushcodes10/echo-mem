---
name: "source-command-agents-agent-spawning"
description: "Migrated source command `agents-agent-spawning`"
---

# source-command-agents-agent-spawning

Use this skill when the user asks to run the migrated source command `agents-agent-spawning`.

## Command Template

# agent-spawning

Guide to spawning agents with Codex's Task tool.

## Using Codex's Task Tool

**CRITICAL**: Always use Codex's Task tool for actual agent execution:

```javascript
// Spawn ALL agents in ONE message
Task("Researcher", "Analyze requirements...", "researcher")
Task("Coder", "Implement features...", "coder")
Task("Tester", "Create tests...", "tester")
```

## MCP Coordination Setup (Optional)

MCP tools are ONLY for coordination:
```javascript
mcp__claude-flow__swarm_init { topology: "mesh" }
mcp__claude-flow__agent_spawn { type: "researcher" }
```

## Best Practices
1. Always spawn agents concurrently
2. Use Task tool for execution
3. MCP only for coordination
4. Batch all operations
