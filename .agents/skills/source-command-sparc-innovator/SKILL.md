---
name: "source-command-sparc-innovator"
description: "Migrated source command `sparc-innovator`"
---

# source-command-sparc-innovator

Use this skill when the user asks to run the migrated source command `sparc-innovator`.

## Command Template

# SPARC Innovator Mode

## Purpose
Creative problem solving with WebSearch and Memory integration.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "innovator",
  task_description: "innovative solutions for scaling",
  options: {
    research_depth: "comprehensive",
    creativity_level: "high"
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run innovator "innovative solutions for scaling"

# For alpha features
npx Codex-flow@alpha sparc run innovator "innovative solutions for scaling"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run innovator "innovative solutions for scaling"
```

## Core Capabilities
- Creative ideation
- Solution brainstorming
- Technology exploration
- Pattern innovation
- Proof of concept

## Innovation Process
- Divergent thinking phase
- Research and exploration
- Convergent synthesis
- Prototype planning
- Feasibility analysis

## Knowledge Sources
- WebSearch for trends
- Memory for context
- Cross-domain insights
- Pattern recognition
- Analogical reasoning
