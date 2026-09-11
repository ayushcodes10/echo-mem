---
name: "source-command-swarm-swarm-init"
description: "Migrated source command `swarm-swarm-init`"
---

# source-command-swarm-swarm-init

Use this skill when the user asks to run the migrated source command `swarm-swarm-init`.

## Command Template

# swarm-init

Initialize a new swarm with specified topology.

## Usage
```bash
npx Codex-flow swarm init [options]
```

## Options
- `--topology <type>` - Swarm topology (mesh, hierarchical, ring, star)
- `--max-agents <n>` - Maximum agents
- `--strategy <type>` - Distribution strategy

## Examples
```bash
npx Codex-flow swarm init --topology mesh
npx Codex-flow swarm init --topology hierarchical --max-agents 8
```
