# Echo Memory

A long-horizon memory architecture for AI agents. Echo Memory is built to remember
everything an agent has ever learned, in the best possible way, and to keep fetching and
writing that memory efficiently no matter how much history accumulates, for coding
tools, chatbots, DevOps agents, or any other agentic system, local or deployed.

## Why

Every AI agent starts from zero unless something remembers what happened last time, and
remembers it well enough and fast enough to still be useful after months or years of
accumulated history. Most memory tools solve short-term recall with plain vector search
over stored facts. That degrades as history grows: more candidates, more noise, slower
retrieval. Echo Memory is built around the read/write algorithm and the data structure
that keeps working at long horizons, not just at day one:

- **A temporal, self-consolidating memory graph.** Facts are edges between entities, not
  flat vector rows. Old, rarely-accessed memory doesn't just accumulate: it gets
  consolidated into higher-level summaries over time (never deleted, always traceable
  back to the original), so retrieval cost stays bounded by what's *currently relevant*,
  not by everything that's *ever* been written. See
  [`docs/designs/echo-memory-design.md`](docs/designs/echo-memory-design.md#long-horizon-memory-architecture)
  for the actual mechanism.
- **Real graph structure, not just similarity.** Multi-hop queries like "how did we end
  up here?", answerable because facts are connected, not just individually embedded.
- **Causal typing, not just similarity.** Edges can be tagged `caused_by`, `led_to`,
  `blocked_by`, `contradicts`, set by the agent's own read of the conversation, not
  inferred statistically. Honest about what's tractable today and what isn't.
- **Auditable by design.** Every change to memory is logged, with a plain-language reason
  you can read back (`echo-memory why <fact_id>`). Memory that consolidates and edits
  itself is only trustworthy if you can see why.
- **One storage engine, every scale.** Postgres + pgvector + Apache AGE, from a single
  local agent up to an organization-wide shared graph spanning every agent a business
  runs. No forced migration later. (The novel work is the memory structure and algorithm
  running on top of Postgres, not a new database engine; see the design doc for why.)
- **Any agent, not one vendor's.** The interface is [MCP](https://modelcontextprotocol.io):
  any MCP-compatible agent can read and write the same memory graph, whether that's a
  coding assistant, a chatbot, an ops agent, or something built in-house.

## Who this is for

- **A developer running local agents** who wants Claude Code, Cursor, or anything else to
  stop losing context between sessions and tools.
- **A team or organization running agentic systems in production** (support bots, DevOps
  agents, internal tooling) that needs a shared memory layer instead of N disconnected
  ones, with the tenancy model (below) to keep it scoped correctly per agent, per team, or
  org-wide.

## Status

Early and staged. See [`docs/designs/`](docs/designs/) for the full architecture and the
v1a → v1b build plan. **The validated wedge driving v1a is specifically cross-tool coding
agent memory** (the founder's own daily pain, real and tested). The broader vision above
is the target this architecture is built toward, not yet something v1a itself proves. v1a
proves basic recall works before v1b adds causal typing and multi-hop graph retrieval, and
before v1.1 adds the org-wide tenancy the broader vision depends on.

## Getting started

The core recall loop is built and running: `write_episode`, `query_memory`,
`get_audit_log`, an MCP server wiring them together, and an `echo-memory` CLI (`why`,
`export`). Full setup is in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md); short version:

```bash
git clone git@github.com:ayushcodes10/echo-mem.git && cd echo-mem
docker compose up -d                       # Postgres + pgvector + Apache AGE
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
alembic upgrade head

claude mcp add --scope user echo-memory \
  -e ECHO_MEMORY_USER_ID=your-user-id \
  -e ECHO_MEMORY_AGENT_ID=claude-code \
  -e ECHO_MEMORY_DATABASE_URL="postgresql://postgres:postgres@localhost:5433/echo_memory" \
  -- "$(pwd)/.venv/bin/python" -m echo_memory.server
```

Start a new Claude Code session and `write_episode`/`query_memory`/`get_audit_log` are
available across every project, not just this repo. See
[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for Cursor/per-repo setup, the
`echo-memory` CLI, and running tests; see
[`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) for using Echo Memory from an agent
that doesn't speak MCP (a chatbot, a DevOps agent, a booking agent, or any custom
tool-calling loop); and see
[`docs/designs/echo-memory-design.md`](docs/designs/echo-memory-design.md) for the
current build plan and progress.

## Architecture

- **Storage:** PostgreSQL with the `pgvector` and Apache AGE extensions
- **Retrieval:** hybrid vector + full-text search (v1a), with Personalized PageRank via
  `networkx` added in v1b for multi-hop associative retrieval
- **Interface:** [Model Context Protocol](https://modelcontextprotocol.io) server:
  `write_episode`, `query_memory`, `get_audit_log`

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Issues and PRs welcome; please read the design
docs first so proposals fit the staged build plan.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
