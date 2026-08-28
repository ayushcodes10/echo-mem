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
- **A write path that costs nothing to run.** Extraction happens in the calling agent,
  never on the server, so recording a memory makes zero LLM calls. Measured locally with
  `echo-memory benchmark`: **write 15ms median, query 8ms, digest 1ms, $0.00 inference
  cost per episode.** The tradeoff is explicit and worth stating: the agent must arrive
  with entities and facts already extracted, which is more work for the caller and the
  reason the [MCP tool contract](docs/DEVELOPMENT.md) spells the shape out. The
  comparison that makes this matter is Zep/Graphiti, the closest architectural match
  (bi-temporal edges, fact invalidation, episode provenance): its own published
  description of ingestion is that "every episode triggers multiple LLM calls for
  extraction, entity resolution, and invalidation" and that "write cost scales with
  volume". Here it doesn't.
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
available across every project, not just this repo.

Prefer it scoped to one project - a single Claude project, a Cursor workspace, a repo
whose memory shouldn't mingle with the rest? `echo-memory install [path] --for
claude|cursor|both` writes a project-scoped MCP config plus a skill (or, for Cursor, an
always-applied rule) telling the agent when to record and when to recall. See
[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for Cursor/per-repo setup, the
`echo-memory` CLI, and running tests; see
[`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) for using Echo Memory from an agent
that doesn't speak MCP (a chatbot, a DevOps agent, a booking agent, or any custom
tool-calling loop); and see
[`docs/designs/echo-memory-design.md`](docs/designs/echo-memory-design.md) for the
current build plan and progress.

## The graph

Memory is a graph, not a list of notes. Entities are nodes; a fact is an **edge**
between two of them. That is the whole data model, and everything below follows
from it.

![The memory graph](docs/images/graph-overview.png)

Three projects here. `checkout-api`, `mobile-app` and `data-pipeline` were
recorded in separate sessions and never told about each other, yet the picture
already separates them — because separation is a property of the edges, not a
label anyone applied.

**Clusters come from structure.** Densely connected facts are grouped by label
propagation over the edges, and each cluster is named after its most-connected
node. That is why `data-pipeline` sits apart on the left: nothing it knows
touches payments. It is also why `checkout-api` and `mobile-app` share a cluster
despite being different codebases — they genuinely do share an idea, and the
graph found it rather than being told.

**Components are the stronger claim.** Two nodes in different components have no
path between them at all, which is the strongest statement this graph can make
that two memories are unrelated.

**Projects are a facet, not the structure.** Every fact records the project it
was written from, and you can colour by it, but project says *where a fact was
written*, not *what it belongs with*.

### Click a node: everything it takes part in

![A node selected](docs/images/graph-node-selected.png)

`idempotency keys` is the concept that joined those two codebases. The panel
shows it referenced from **checkout-api twice and mobile-app once**, the three
facts it appears in, and how the node itself resolved — each mention matched an
existing node by exact name rather than creating a duplicate.

Nobody wrote "these projects are related." Two sessions independently recorded a
fact about idempotency keys, entity resolution matched them to one node, and the
relationship exists as a consequence.

### Click a link: why memory believes it

![A fact selected](docs/images/graph-fact-selected.png)

This is what a knowledge graph gives you that a code map cannot. Selecting the
edge answers, for that single fact:

| | |
|---|---|
| **what** | the sentence, its `relation_type`, and how confidently it was stated |
| **when** | when it became valid, and when it was superseded if it has been |
| **who** | which agent wrote it, in which session |
| **where** | which project it came from |
| **why** | the audit trail — created, superseded from what to what, and the entity-resolution rationale for the nodes at either end |

A superseded fact is never deleted. It stops being drawn, because the graph no
longer asserts that relationship, but it stays reachable from its node and keeps
its full history. `echo-memory why <fact_id>` prints the same trail in a terminal.

### Seeing your own

```bash
echo-memory dashboard --serve --open
```

The images above come from a synthetic dataset (`scripts/demo-seed.py`) rather
than a real store, for the obvious reason: a real memory graph is full of
hostnames, account numbers and client names.

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
