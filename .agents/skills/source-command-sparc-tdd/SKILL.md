---
name: "source-command-sparc-tdd"
description: "Migrated source command `sparc-tdd`"
---

# source-command-sparc-tdd

Use this skill when the user asks to run the migrated source command `sparc-tdd`.

## Command Template

# SPARC TDD Mode

## Purpose
Test-driven development with TodoWrite planning and comprehensive testing.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "tdd",
  task_description: "shopping cart feature",
  options: {
    coverage_target: 90,
    test_framework: "jest"
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run tdd "shopping cart feature"

# For alpha features
npx Codex-flow@alpha sparc run tdd "shopping cart feature"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run tdd "shopping cart feature"
```

## Core Capabilities
- Test-first development
- Red-green-refactor cycle
- Test suite design
- Coverage optimization
- Continuous testing

## TDD Workflow
1. Write failing tests
2. Implement minimum code
3. Make tests pass
4. Refactor code
5. Repeat cycle

## Testing Strategies
- Unit testing
- Integration testing
- End-to-end testing
- Performance testing
- Security testing
