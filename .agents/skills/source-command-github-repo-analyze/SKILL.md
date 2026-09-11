---
name: "source-command-github-repo-analyze"
description: "Migrated source command `github-repo-analyze`"
---

# source-command-github-repo-analyze

Use this skill when the user asks to run the migrated source command `github-repo-analyze`.

## Command Template

# repo-analyze

Deep analysis of GitHub repository with AI insights.

## Usage
```bash
npx Codex-flow github repo-analyze [options]
```

## Options
- `--repository <owner/repo>` - Repository to analyze
- `--deep` - Enable deep analysis
- `--include <areas>` - Include specific areas (issues, prs, code, commits)

## Examples
```bash
# Basic analysis
npx Codex-flow github repo-analyze --repository myorg/myrepo

# Deep analysis
npx Codex-flow github repo-analyze --repository myorg/myrepo --deep

# Specific areas
npx Codex-flow github repo-analyze --repository myorg/myrepo --include issues,prs
```
