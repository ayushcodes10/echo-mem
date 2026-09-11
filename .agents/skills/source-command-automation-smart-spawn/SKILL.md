---
name: "source-command-automation-smart-spawn"
description: "Migrated source command `automation-smart-spawn`"
---

# source-command-automation-smart-spawn

Use this skill when the user asks to run the migrated source command `automation-smart-spawn`.

## Command Template

# smart-spawn

Intelligently spawn agents based on workload analysis.

## Usage
```bash
npx Codex-flow automation smart-spawn [options]
```

## Options
- `--analyze` - Analyze before spawning
- `--threshold <n>` - Spawn threshold
- `--topology <type>` - Preferred topology

## Examples
```bash
# Smart spawn with analysis
npx Codex-flow automation smart-spawn --analyze

# Set spawn threshold
npx Codex-flow automation smart-spawn --threshold 5

# Force topology
npx Codex-flow automation smart-spawn --topology hierarchical
```
