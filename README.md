# Echo Memory

A graph memory layer for AI coding agents. Echo Memory gives agents like Claude Code and
Cursor a shared, persistent memory so you stop re-explaining context every time you switch
tools.

## Why

Switching between AI coding tools loses context. You made a decision with one agent
yesterday; today's agent has no idea it happened. Most memory tools for AI agents solve
this with plain vector search over stored facts. Echo Memory goes further:

- **Real graph structure.** Facts are edges between entities, not flat rows in a vector
  index — enabling multi-hop queries like "how did we end up here?"
- **Causal typing, not just similarity.** Edges can be tagged `caused_by`, `led_to`,
  `blocked_by`, `contradicts` — set by the agent's own read of the conversation, not
  inferred statistically. Honest about what's tractable today and what isn't.
- **Auditable by design.** Every change to memory is logged, with a plain-language reason
  you can read back (`echo-memory why <fact_id>`) — memory that edits itself is only
  trustworthy if you can see why.
- **One storage engine, every scale.** Postgres + pgvector + Apache AGE, from a single
  local agent up to an organization-wide shared graph. No forced migration later.

## Status

Early and staged. See [`docs/designs/`](docs/designs/) for the full architecture and the
v1a → v1b build plan. v1a proves basic cross-tool recall works before v1b adds causal
typing and multi-hop graph retrieval on top.

## Getting started

Not yet ready for use — see [`docs/designs/echo-memory-design.md`](docs/designs/echo-memory-design.md)
for the current build plan and progress, and [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)
for the local setup once code exists.

## Architecture

- **Storage:** PostgreSQL with the `pgvector` and Apache AGE extensions
- **Retrieval:** hybrid vector + full-text search (v1a), with Personalized PageRank via
  `networkx` added in v1b for multi-hop associative retrieval
- **Interface:** [Model Context Protocol](https://modelcontextprotocol.io) server —
  `write_episode`, `query_memory`, `get_audit_log`

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Issues and PRs welcome — please read the design
docs first so proposals fit the staged build plan.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
