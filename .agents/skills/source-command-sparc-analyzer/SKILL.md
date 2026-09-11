---
name: "source-command-sparc-analyzer"
description: "Migrated source command `sparc-analyzer`"
---

# source-command-sparc-analyzer

Use this skill when the user asks to run the migrated source command `sparc-analyzer`.

## Command Template

# SPARC Analyzer Mode

## Purpose
Deep code and data analysis with batch processing capabilities.

## Activation

### Option 1: Using MCP Tools (Preferred in Codex)
```javascript
mcp__claude-flow__sparc_mode {
  mode: "analyzer",
  task_description: "analyze codebase performance",
  options: {
    parallel: true,
    detailed: true
  }
}
```

### Option 2: Using NPX CLI (Fallback when MCP not available)
```bash
# Use when running from terminal or MCP tools unavailable
npx Codex-flow sparc run analyzer "analyze codebase performance"

# For alpha features
npx Codex-flow@alpha sparc run analyzer "analyze codebase performance"
```

### Option 3: Local Installation
```bash
# If Codex-flow is installed locally
./Codex-flow sparc run analyzer "analyze codebase performance"
```

## Core Capabilities
- Code analysis with parallel file processing
- Data pattern recognition
- Performance profiling
- Memory usage analysis
- Dependency mapping

## Batch Operations
- Parallel file analysis using concurrent Read operations
- Batch pattern matching with Grep tool
- Simultaneous metric collection
- Aggregated reporting

## Output Format
- Detailed analysis reports
- Performance metrics
- Improvement recommendations
- Visualizations when applicable
