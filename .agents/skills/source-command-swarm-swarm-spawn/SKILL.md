---
name: "source-command-swarm-swarm-spawn"
description: "Migrated source command `swarm-swarm-spawn`"
---

# source-command-swarm-swarm-spawn

Use this skill when the user asks to run the migrated source command `swarm-swarm-spawn`.

## Command Template

# swarm-spawn

Spawn agents in the swarm.

## Usage
```bash
npx Codex-flow swarm spawn [options]
```

## Options
- `--type <type>` - Agent type
- `--count <n>` - Number to spawn
- `--capabilities <list>` - Agent capabilities

## Examples
```bash
npx Codex-flow swarm spawn --type coder --count 3
npx Codex-flow swarm spawn --type researcher --capabilities "web-search,analysis"
```
