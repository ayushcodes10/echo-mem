---
name: "source-command-memory-memory-persist"
description: "Migrated source command `memory-memory-persist`"
---

# source-command-memory-memory-persist

Use this skill when the user asks to run the migrated source command `memory-memory-persist`.

## Command Template

# memory-persist

Persist memory across sessions.

## Usage
```bash
npx Codex-flow memory persist [options]
```

## Options
- `--export <file>` - Export to file
- `--import <file>` - Import from file
- `--compress` - Compress memory data

## Examples
```bash
# Export memory
npx Codex-flow memory persist --export memory-backup.json

# Import memory
npx Codex-flow memory persist --import memory-backup.json

# Compressed export
npx Codex-flow memory persist --export memory.gz --compress
```
