---
name: "source-command-sparc-designer"
description: "Migrated source command `sparc-designer`"
---

# source-command-sparc-designer

Use this skill when the user asks to run the migrated source command `sparc-designer`.

## Command Template

# SPARC Designer Mode

## Purpose
UI/UX design with Memory coordination for consistent experiences.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "designer",
  task_description: "create dashboard UI",
  options: {
    design_system: true,
    responsive: true
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run designer "create dashboard UI"

# For alpha features
npx Codex-flow@alpha sparc run designer "create dashboard UI"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run designer "create dashboard UI"
```

## Core Capabilities
- Interface design
- Component architecture
- Design system creation
- Accessibility planning
- Responsive layouts

## Design Process
- User research insights
- Wireframe creation
- Component design
- Interaction patterns
- Design token management

## Memory Coordination
- Store design decisions
- Share component specs
- Maintain consistency
- Track design evolution
