---
name: "source-command-sparc-debugger"
description: "Migrated source command `sparc-debugger`"
---

# source-command-sparc-debugger

Use this skill when the user asks to run the migrated source command `sparc-debugger`.

## Command Template

# SPARC Debugger Mode

## Purpose
Systematic debugging with TodoWrite and Memory integration.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "debugger",
  task_description: "fix authentication issues",
  options: {
    verbose: true,
    trace: true
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run debugger "fix authentication issues"

# For alpha features
npx Codex-flow@alpha sparc run debugger "fix authentication issues"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run debugger "fix authentication issues"
```

## Core Capabilities
- Issue reproduction
- Root cause analysis
- Stack trace analysis
- Memory leak detection
- Performance bottleneck identification

## Debugging Workflow
1. Create debugging plan with TodoWrite
2. Systematic issue investigation
3. Store findings in Memory
4. Track fix progress
5. Verify resolution

## Tools Integration
- Error log analysis
- Breakpoint simulation
- Variable inspection
- Call stack tracing
- Memory profiling
