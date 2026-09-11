---
name: "source-command-sparc-batch-executor"
description: "Migrated source command `sparc-batch-executor`"
---

# source-command-sparc-batch-executor

Use this skill when the user asks to run the migrated source command `sparc-batch-executor`.

## Command Template

# SPARC Batch Executor Mode

## Purpose
Parallel task execution specialist using batch operations.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "batch-executor",
  task_description: "process multiple files",
  options: {
    parallel: true,
    batch_size: 10
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run batch-executor "process multiple files"

# For alpha features
npx Codex-flow@alpha sparc run batch-executor "process multiple files"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run batch-executor "process multiple files"
```

## Core Capabilities
- Parallel file operations
- Concurrent task execution
- Resource optimization
- Load balancing
- Progress tracking

## Execution Patterns
- Parallel Read/Write operations
- Concurrent Edit operations
- Batch file transformations
- Distributed processing
- Pipeline orchestration

## Performance Features
- Dynamic resource allocation
- Automatic load balancing
- Progress monitoring
- Error recovery
- Result aggregation
