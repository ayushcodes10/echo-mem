---
name: "source-command-sparc-coder"
description: "Migrated source command `sparc-coder`"
---

# source-command-sparc-coder

Use this skill when the user asks to run the migrated source command `sparc-coder`.

## Command Template

# SPARC Coder Mode

## Purpose
Autonomous code generation with batch file operations.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "coder",
  task_description: "implement user authentication",
  options: {
    test_driven: true,
    parallel_edits: true
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run coder "implement user authentication"

# For alpha features
npx Codex-flow@alpha sparc run coder "implement user authentication"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run coder "implement user authentication"
```

## Core Capabilities
- Feature implementation
- Code refactoring
- Bug fixes
- API development
- Algorithm implementation

## Batch Operations
- Parallel file creation
- Concurrent code modifications
- Batch import updates
- Test file generation
- Documentation updates

## Code Quality
- ES2022 standards
- Type safety with TypeScript
- Comprehensive error handling
- Performance optimization
- Security best practices
