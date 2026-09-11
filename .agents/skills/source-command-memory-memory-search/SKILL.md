---
name: "source-command-memory-memory-search"
description: "Migrated source command `memory-memory-search`"
---

# source-command-memory-memory-search

Use this skill when the user asks to run the migrated source command `memory-memory-search`.

## Command Template

# memory-search

Search through stored memory.

## Usage
```bash
npx Codex-flow memory search [options]
```

## Options
- `--query <text>` - Search query
- `--pattern <regex>` - Pattern matching
- `--limit <n>` - Result limit

## Examples
```bash
# Search memory
npx Codex-flow memory search --query "authentication"

# Pattern search
npx Codex-flow memory search --pattern "api-.*"

# Limited results
npx Codex-flow memory search --query "config" --limit 10
```
