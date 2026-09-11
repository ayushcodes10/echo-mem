---
name: "source-command-analysis-performance-report"
description: "Migrated source command `analysis-performance-report`"
---

# source-command-analysis-performance-report

Use this skill when the user asks to run the migrated source command `analysis-performance-report`.

## Command Template

# performance-report

Generate comprehensive performance reports for swarm operations.

## Usage
```bash
npx Codex-flow analysis performance-report [options]
```

## Options
- `--format <type>` - Report format (json, html, markdown)
- `--include-metrics` - Include detailed metrics
- `--compare <id>` - Compare with previous swarm

## Examples
```bash
# Generate HTML report
npx Codex-flow analysis performance-report --format html

# Compare swarms
npx Codex-flow analysis performance-report --compare swarm-123

# Full metrics report
npx Codex-flow analysis performance-report --include-metrics --format markdown
```
