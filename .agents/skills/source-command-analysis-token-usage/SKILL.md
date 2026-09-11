---
name: "source-command-analysis-token-usage"
description: "Migrated source command `analysis-token-usage`"
---

# source-command-analysis-token-usage

Use this skill when the user asks to run the migrated source command `analysis-token-usage`.

## Command Template

# token-usage

Analyze token usage patterns and optimize for efficiency.

## Usage
```bash
npx Codex-flow analysis token-usage [options]
```

## Options
- `--period <time>` - Analysis period (1h, 24h, 7d, 30d)
- `--by-agent` - Break down by agent
- `--by-operation` - Break down by operation type

## Examples
```bash
# Last 24 hours token usage
npx Codex-flow analysis token-usage --period 24h

# By agent breakdown
npx Codex-flow analysis token-usage --by-agent

# Export detailed report
npx Codex-flow analysis token-usage --period 7d --export tokens.csv
```
