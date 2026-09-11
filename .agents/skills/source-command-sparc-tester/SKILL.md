---
name: "source-command-sparc-tester"
description: "Migrated source command `sparc-tester`"
---

# source-command-sparc-tester

Use this skill when the user asks to run the migrated source command `sparc-tester`.

## Command Template

# SPARC Tester Mode

## Purpose
Comprehensive testing with parallel execution capabilities.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "tester",
  task_description: "full regression suite",
  options: {
    parallel: true,
    coverage: true
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run tester "full regression suite"

# For alpha features
npx Codex-flow@alpha sparc run tester "full regression suite"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run tester "full regression suite"
```

## Core Capabilities
- Test planning
- Test execution
- Bug detection
- Coverage analysis
- Report generation

## Test Types
- Unit tests
- Integration tests
- E2E tests
- Performance tests
- Security tests

## Parallel Features
- Concurrent test runs
- Distributed testing
- Load testing
- Cross-browser testing
- Multi-environment validation
