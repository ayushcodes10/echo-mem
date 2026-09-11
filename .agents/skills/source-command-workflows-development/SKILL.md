---
name: "source-command-workflows-development"
description: "Migrated source command `workflows-development`"
---

# source-command-workflows-development

Use this skill when the user asks to run the migrated source command `workflows-development`.

## Command Template

# Development Workflow Coordination

## Purpose
Structure Codex's approach to complex development tasks for maximum efficiency.

## Step-by-Step Coordination

### 1. Initialize Development Framework
```
Tool: mcp__claude-flow__swarm_init
Parameters: {"topology": "hierarchical", "maxAgents": 8, "strategy": "specialized"}
```
Creates hierarchical structure for organized, top-down development.

### 2. Define Development Perspectives
```
Tool: mcp__claude-flow__agent_spawn
Parameters: {
  "type": "architect",
  "name": "System Design",
  "capabilities": ["api-design", "database-schema"]
}
```
```
Tool: mcp__claude-flow__agent_spawn
Parameters: {
  "type": "coder",
  "name": "Implementation Focus",
  "capabilities": ["nodejs", "typescript", "express"]
}
```
```
Tool: mcp__claude-flow__agent_spawn
Parameters: {
  "type": "tester",
  "name": "Quality Assurance",
  "capabilities": ["unit-testing", "integration-testing"]
}
```
Sets up architectural and implementation thinking patterns.

### 3. Coordinate Implementation
```
Tool: mcp__claude-flow__task_orchestrate
Parameters: {
  "task": "Build REST API with authentication",
  "strategy": "parallel",
  "priority": "high",
  "dependencies": ["database setup", "auth system"]
}
```

### 4. Monitor Progress
```
Tool: mcp__claude-flow__task_status
Parameters: {"taskId": "api-build-task-123"}
```

## What Codex Actually Does
1. Uses **Write** tool to create new files
2. Uses **Edit/MultiEdit** tools for code modifications
3. Uses **Bash** tool for testing and building
4. Uses **TodoWrite** tool for task tracking
5. Follows coordination patterns for systematic implementation

Remember: All code is written by Codex using its native tools!

## CLI Usage
```bash
# Start development workflow via CLI
npx Codex-flow workflow dev "REST API with auth"

# Create custom workflow
npx Codex-flow workflow create --name "api-dev" --steps "design,implement,test,deploy"

# Execute saved workflow
npx Codex-flow workflow execute api-dev
```
