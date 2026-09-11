---
name: "source-command-sparc-optimizer"
description: "Migrated source command `sparc-optimizer`"
---

# source-command-sparc-optimizer

Use this skill when the user asks to run the migrated source command `sparc-optimizer`.

## Command Template

# SPARC Optimizer Mode

## Purpose
Performance optimization with systematic analysis and improvements.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "optimizer",
  task_description: "optimize application performance",
  options: {
    profile: true,
    benchmark: true
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run optimizer "optimize application performance"

# For alpha features
npx Codex-flow@alpha sparc run optimizer "optimize application performance"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run optimizer "optimize application performance"
```

## Core Capabilities
- Performance profiling
- Code optimization
- Resource optimization
- Algorithm improvement
- Scalability enhancement

## Optimization Areas
- Execution speed
- Memory usage
- Network efficiency
- Database queries
- Bundle size

## Systematic Approach
1. Baseline measurement
2. Bottleneck identification
3. Optimization implementation
4. Impact verification
5. Continuous monitoring
