# Contributing to Echo Memory

Thanks for considering a contribution. This project is early and staged; please read
[`docs/designs/echo-memory-design.md`](docs/designs/echo-memory-design.md) before
proposing anything, so your PR fits the current build phase (v1a → v1b → v1.1, in that
order, each gated on the previous one's exit criteria).

## Before you start

- **Check the PR plan** in the design doc for the current dependency-ordered sequence.
  Work that jumps ahead of a gate (e.g. v1b work before v1a's exit criteria are met)
  will likely be asked to wait, not because the idea is bad but because the point of the
  staging is to validate each layer before building the next.
- **Open an issue before a large PR.** Small fixes and docs improvements don't need
  this; anything touching schema, retrieval logic, or the MCP contract should get a
  quick discussion first.

## Development setup

See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Commit messages

Short, imperative, and specific. `fix entity resolution off-by-one in threshold check`,
not `fix bug`. No AI-tool attribution in commit messages or co-author trailers.

## Pull requests

- Keep PRs scoped to one thing; this project intentionally uses small, independently
  reviewable PRs rather than large landings (see the design doc's PR plan).
- Every new codepath needs a test. Deterministic logic gets a unit test; anything
  depending on LLM judgment (entity resolution's fuzzy-match confirm, `causal_hint`
  classification) goes through the eval suite instead of a mocked unit test; see
  `docs/DEVELOPMENT.md`'s test-strategy note.
- CI must pass before merge.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).

## Reporting security issues

See [`SECURITY.md`](SECURITY.md). Do not open a public issue for a security
vulnerability.
