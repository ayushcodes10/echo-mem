---
name: "source-command-workflows-research"
description: "Migrated source command `workflows-research`"
---

# source-command-workflows-research

Use this skill when the user asks to run the migrated source command `workflows-research`.

## Command Template

# Research Workflow Coordination

## Purpose
Coordinate Codex's research activities for comprehensive, systematic exploration.

## Step-by-Step Coordination

### 1. Initialize Research Framework
```
Tool: mcp__claude-flow__swarm_init
Parameters: {"topology": "mesh", "maxAgents": 5, "strategy": "balanced"}
```
Creates a mesh topology for comprehensive exploration from multiple angles.

### 2. Define Research Perspectives
```
Tool: mcp__claude-flow__agent_spawn
Parameters: {"type": "researcher", "name": "Literature Review"}
```
```
Tool: mcp__claude-flow__agent_spawn  
Parameters: {"type": "analyst", "name": "Data Analysis"}
```
Sets up different analytical approaches for Codex to use.

### 3. Execute Coordinated Research
```
Tool: mcp__claude-flow__task_orchestrate
Parameters: {
  "task": "Research modern web frameworks performance",
  "strategy": "adaptive",
  "priority": "medium"
}
```

### 4. Store Research Findings
```
Tool: mcp__claude-flow__memory_usage
Parameters: {
  "action": "store",
  "key": "research_findings",
  "value": "framework performance analysis results",
  "namespace": "research"
}
```

## What Codex Actually Does
1. Uses **WebSearch** tool for finding resources
2. Uses **Read** tool for analyzing documentation
3. Uses **Task** tool for parallel exploration
4. Synthesizes findings using coordination patterns
5. Stores insights in memory for future reference

Remember: The swarm coordinates HOW Codex researches, not WHAT it finds.

## CLI Usage
```bash
# Start research workflow via CLI
npx Codex-flow workflow research "modern web frameworks"

# Export research workflow
npx Codex-flow workflow export research --format json
```
