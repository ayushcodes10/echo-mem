---
name: "source-command-github-pr-enhance"
description: "Migrated source command `github-pr-enhance`"
---

# source-command-github-pr-enhance

Use this skill when the user asks to run the migrated source command `github-pr-enhance`.

## Command Template

# pr-enhance

AI-powered pull request enhancements.

## Usage
```bash
npx Codex-flow github pr-enhance [options]
```

## Options
- `--pr-number <n>` - Pull request number
- `--add-tests` - Add missing tests
- `--improve-docs` - Improve documentation
- `--check-security` - Security review

## Examples
```bash
# Enhance PR
npx Codex-flow github pr-enhance --pr-number 123

# Add tests
npx Codex-flow github pr-enhance --pr-number 123 --add-tests

# Full enhancement
npx Codex-flow github pr-enhance --pr-number 123 --add-tests --improve-docs
```
