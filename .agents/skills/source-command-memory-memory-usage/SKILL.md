---
name: "source-command-memory-memory-usage"
description: "Migrated source command `memory-memory-usage`"
---

# source-command-memory-memory-usage

Use this skill when the user asks to run the migrated source command `memory-memory-usage`.

## Command Template

# memory-usage

Manage persistent memory storage.

## Usage
```bash
npx Codex-flow memory usage [options]
```

## Options
- `--action <type>` - Action (store, retrieve, list, clear)
- `--key <key>` - Memory key
- `--value <data>` - Data to store (JSON)

## Examples
```bash
# Store memory
npx Codex-flow memory usage --action store --key "project-config" --value '{"api": "v2"}'

# Retrieve memory
npx Codex-flow memory usage --action retrieve --key "project-config"

# List all keys
npx Codex-flow memory usage --action list
```
