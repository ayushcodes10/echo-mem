---
name: "source-command-optimization-topology-optimize"
description: "Migrated source command `optimization-topology-optimize`"
---

# source-command-optimization-topology-optimize

Use this skill when the user asks to run the migrated source command `optimization-topology-optimize`.

## Command Template

# topology-optimize

Optimize swarm topology for current workload.

## Usage
```bash
npx Codex-flow optimization topology-optimize [options]
```

## Options
- `--analyze-first` - Analyze before optimizing
- `--target <metric>` - Optimization target
- `--apply` - Apply optimizations

## Examples
```bash
# Analyze and suggest
npx Codex-flow optimization topology-optimize --analyze-first

# Optimize for speed
npx Codex-flow optimization topology-optimize --target speed

# Apply changes
npx Codex-flow optimization topology-optimize --target efficiency --apply
```
