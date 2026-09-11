---
name: "source-command-github-issue-triage"
description: "Migrated source command `github-issue-triage`"
---

# source-command-github-issue-triage

Use this skill when the user asks to run the migrated source command `github-issue-triage`.

## Command Template

# issue-triage

Intelligent issue classification and triage.

## Usage
```bash
npx Codex-flow github issue-triage [options]
```

## Options
- `--repository <owner/repo>` - Target repository
- `--auto-label` - Automatically apply labels
- `--assign` - Auto-assign to team members

## Examples
```bash
# Triage issues
npx Codex-flow github issue-triage --repository myorg/myrepo

# With auto-labeling
npx Codex-flow github issue-triage --repository myorg/myrepo --auto-label

# Full automation
npx Codex-flow github issue-triage --repository myorg/myrepo --auto-label --assign
```
