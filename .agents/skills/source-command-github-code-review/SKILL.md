---
name: "source-command-github-code-review"
description: "Migrated source command `github-code-review`"
---

# source-command-github-code-review

Use this skill when the user asks to run the migrated source command `github-code-review`.

## Command Template

# code-review

Automated code review with swarm intelligence.

## Usage
```bash
npx Codex-flow github code-review [options]
```

## Options
- `--pr-number <n>` - Pull request to review
- `--focus <areas>` - Review focus (security, performance, style)
- `--suggest-fixes` - Suggest code fixes

## Examples
```bash
# Review PR
npx Codex-flow github code-review --pr-number 456

# Security focus
npx Codex-flow github code-review --pr-number 456 --focus security

# With fix suggestions
npx Codex-flow github code-review --pr-number 456 --suggest-fixes
```
