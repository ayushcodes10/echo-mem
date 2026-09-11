---
name: "source-command-hooks-overview"
description: "Migrated source command `hooks-overview`"
---

# source-command-hooks-overview

Use this skill when the user asks to run the migrated source command `hooks-overview`.

## Command Template

# Codex Hooks for Codex-flow

## Purpose
Automatically coordinate, format, and learn from Codex operations using hooks.

## Available Hooks

### Pre-Operation Hooks
- **pre-edit**: Validate and assign agents before file modifications
- **pre-bash**: Check command safety and resource requirements
- **pre-task**: Auto-spawn agents for complex tasks

### Post-Operation Hooks
- **post-edit**: Auto-format code and train neural patterns
- **post-bash**: Log execution and update metrics
- **post-search**: Cache results and improve search patterns

### MCP Integration Hooks
- **mcp-initialized**: Persist swarm configuration
- **agent-spawned**: Update agent roster
- **task-orchestrated**: Monitor task progress
- **neural-trained**: Save pattern improvements

### Session Hooks
- **notify**: Custom notifications with swarm status
- **session-end**: Generate summary and save state
- **session-restore**: Load previous session state

## Configuration
Hooks are configured in `.Codex/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "^(Write|Edit|MultiEdit)$",
        "hooks": [{
          "type": "command",
          "command": "npx Codex-flow hook pre-edit --file '${tool.params.file_path}'"
        }]
      }
    ]
  }
}
```

## Benefits
- 🤖 Automatic agent assignment based on file type
- 🎨 Consistent code formatting
- 🧠 Continuous neural pattern improvement
- 💾 Cross-session memory persistence
- 📊 Performance metrics tracking

## See Also
- [Pre-Edit Hook](./pre-edit.md)
- [Post-Edit Hook](./post-edit.md)
- [Session End Hook](./session-end.md)
