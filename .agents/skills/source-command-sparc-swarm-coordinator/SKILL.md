---
name: "source-command-sparc-swarm-coordinator"
description: "Migrated source command `sparc-swarm-coordinator`"
---

# source-command-sparc-swarm-coordinator

Use this skill when the user asks to run the migrated source command `sparc-swarm-coordinator`.

## Command Template

# SPARC Swarm Coordinator Mode

## Purpose
Specialized swarm management with batch coordination capabilities.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "swarm-coordinator",
  task_description: "manage development swarm",
  options: {
    topology: "hierarchical",
    max_agents: 10
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run swarm-coordinator "manage development swarm"

# For alpha features
npx Codex-flow@alpha sparc run swarm-coordinator "manage development swarm"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run swarm-coordinator "manage development swarm"
```

## Core Capabilities
- Swarm initialization
- Agent management
- Task distribution
- Load balancing
- Result collection

## Coordination Modes
- Hierarchical swarms
- Mesh networks
- Pipeline coordination
- Adaptive strategies
- Hybrid approaches

## Management Features
- Dynamic scaling
- Resource optimization
- Failure recovery
- Performance monitoring
- Quality assurance
