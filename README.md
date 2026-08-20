# Echo Memory

A graph memory layer for AI agents — coding tools, chatbots, DevOps agents, any agentic
system, local or deployed. Echo Memory gives agents a shared, persistent memory so context
survives across sessions, across tools, and across an entire organization's agents, instead
of resetting every time.

## Why

Every AI agent starts from zero unless something remembers what happened last time — and
remembers it in a form another agent can actually use. A coding agent that made a decision
yesterday, a support chatbot that resolved a customer's issue last week, a DevOps agent
that diagnosed a deployment failure last month — none of that persists or transfers today.
Most memory tools for AI agents solve this with plain vector search over stored facts.
Echo Memory goes further:

- **Real graph structure.** Facts are edges between entities, not flat rows in a vector
  index — enabling multi-hop queries like "how did we end up here?"
- **Causal typing, not just similarity.** Edges can be tagged `caused_by`, `led_to`,
  `blocked_by`, `contradicts` — set by the agent's own read of the conversation, not
  inferred statistically. Honest about what's tractable today and what isn't.
- **Auditable by design.** Every change to memory is logged, with a plain-language reason
  you can read back (`echo-memory why <fact_id>`) — memory that edits itself is only
  trustworthy if you can see why.
- **One storage engine, every scale.** Postgres + pgvector + Apache AGE, from a single
  local agent up to an organization-wide shared graph spanning every agent a business
  runs. No forced migration later.
- **Any agent, not one vendor's.** The interface is [MCP](https://modelcontextprotocol.io)
  — any MCP-compatible agent can read and write the same memory graph, whether that's a
  coding assistant, a chatbot, an ops agent, or something built in-house.

## Who this is for

- **A developer running local agents** who wants Claude Code, Cursor, or anything else to
  stop losing context between sessions and tools.
- **A team or organization running agentic systems in production** — support bots, DevOps
  agents, internal tooling — that need a shared memory layer instead of N disconnected
  ones, with the tenancy model (below) to keep it scoped correctly per agent, per team, or
  org-wide.

## Status

Early and staged. See [`docs/designs/`](docs/designs/) for the full architecture and the
v1a → v1b build plan. **The validated wedge driving v1a is specifically cross-tool coding
agent memory** (the founder's own daily pain, real and tested) — the broader vision above
is the target this architecture is built toward, not yet something v1a itself proves. v1a
proves basic recall works before v1b adds causal typing and multi-hop graph retrieval, and
before v1.1 adds the org-wide tenancy the broader vision depends on.

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
