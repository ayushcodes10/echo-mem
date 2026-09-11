---
name: "source-command-optimization-cache-manage"
description: "Migrated source command `optimization-cache-manage`"
---

# source-command-optimization-cache-manage

Use this skill when the user asks to run the migrated source command `optimization-cache-manage`.

## Command Template

# cache-manage

Manage operation cache for performance.

## Usage
```bash
npx Codex-flow optimization cache-manage [options]
```

## Options
- `--action <type>` - Action (view, clear, optimize)
- `--max-size <mb>` - Maximum cache size
- `--ttl <seconds>` - Time to live

## Examples
```bash
# View cache stats
npx Codex-flow optimization cache-manage --action view

# Clear cache
npx Codex-flow optimization cache-manage --action clear

# Set limits
npx Codex-flow optimization cache-manage --max-size 100 --ttl 3600
```
