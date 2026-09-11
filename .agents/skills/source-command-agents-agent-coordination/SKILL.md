---
name: "source-command-agents-agent-coordination"
description: "Migrated source command `agents-agent-coordination`"
---

# source-command-agents-agent-coordination

Use this skill when the user asks to run the migrated source command `agents-agent-coordination`.

## Command Template

# agent-coordination

Coordination patterns for multi-agent collaboration.

## Coordination Patterns

### Hierarchical
Queen-led with worker specialization
```bash
npx Codex-flow swarm init --topology hierarchical
```

### Mesh
Peer-to-peer collaboration
```bash
npx Codex-flow swarm init --topology mesh
```

### Adaptive
Dynamic topology based on workload
```bash
npx Codex-flow swarm init --topology adaptive
```

## Best Practices
- Use hierarchical for complex projects
- Use mesh for research tasks
- Use adaptive for unknown workloads
