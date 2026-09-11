---
name: "source-command-coordination-swarm-init"
description: "Migrated source command `coordination-swarm-init`"
---

# source-command-coordination-swarm-init

Use this skill when the user asks to run the migrated source command `coordination-swarm-init`.

## Command Template

# swarm init

Initialize a Codex Flow swarm with specified topology and configuration.

## Usage

```bash
npx Codex-flow swarm init [options]
```

## Options

- `--topology, -t <type>` - Swarm topology: mesh, hierarchical, ring, star (default: hierarchical)
- `--max-agents, -m <number>` - Maximum number of agents (default: 8)
- `--strategy, -s <type>` - Execution strategy: balanced, parallel, sequential (default: parallel)
- `--auto-spawn` - Automatically spawn agents based on task complexity
- `--memory` - Enable cross-session memory persistence
- `--github` - Enable GitHub integration features

## Examples

### Basic initialization

```bash
npx Codex-flow swarm init
```

### Mesh topology for research

```bash
npx Codex-flow swarm init --topology mesh --max-agents 5 --strategy balanced
```

### Hierarchical for development

```bash
npx Codex-flow swarm init --topology hierarchical --max-agents 10 --strategy parallel --auto-spawn
```

### GitHub-focused swarm

```bash
npx Codex-flow swarm init --topology star --github --memory
```

## Topologies

### Mesh

- All agents connect to all others
- Best for: Research, exploration, brainstorming
- Communication: High overhead, maximum information sharing

### Hierarchical

- Tree structure with clear command chain
- Best for: Development, structured tasks, large projects
- Communication: Efficient, clear responsibilities

### Ring

- Agents connect in a circle
- Best for: Pipeline processing, sequential workflows
- Communication: Low overhead, ordered processing

### Star

- Central coordinator with satellite agents
- Best for: Simple tasks, centralized control
- Communication: Minimal overhead, clear coordination

## Integration with Codex

Once initialized, use MCP tools in Codex:

```javascript
mcp__claude-flow__swarm_init { topology: "hierarchical", maxAgents: 8 }
```

## See Also

- `agent spawn` - Create swarm agents
- `task orchestrate` - Coordinate task execution
- `swarm status` - Check swarm state
- `swarm monitor` - Real-time monitoring
