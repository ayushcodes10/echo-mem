# Local Development

## Prerequisites

- Python 3.11+
- Docker and Docker Compose

No API key needed for v1a: extraction happens in the calling agent (not this server),
and embeddings use a local `sentence-transformers` model. See the design doc's MCP tool
contract section for why.

## First-time setup

```bash
git clone git@github.com:ayushcodes10/echo-mem.git
cd echo-mem

# Start Postgres with pgvector + Apache AGE (built from source on top of
# pgvector/pgvector:pg16, not the apache/age image; see docker/postgres.Dockerfile
# and the design doc's Foundational spike section for why)
docker compose up -d

# Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# edit .env: set ECHO_MEMORY_USER_ID, ECHO_MEMORY_AGENT_ID, ECHO_MEMORY_DATABASE_URL

# Apply migrations
alembic upgrade head
```

## Running the MCP server locally

```bash
python -m echo_memory.server
```

Runs over stdio (the `mcp` SDK's default transport), not a network listener, so there's
nothing to bind or expose beyond the local process. Each client should run its own
instance with a distinct `ECHO_MEMORY_AGENT_ID`; see the design doc's "Configuration"
section for how `scope: "solo" | "shared"` resolves per agent.

### Registering with Claude Code

Recommended: **user scope**, so the server is available across every project you work
in, not just this repo. The actual wedge use case (cross-tool memory) only shows up
under real, ambient usage, not usage confined to working on Echo Memory itself.

```bash
claude mcp add --scope user echo-memory \
  -e ECHO_MEMORY_USER_ID=your-user-id \
  -e ECHO_MEMORY_AGENT_ID=claude-code \
  -e ECHO_MEMORY_DATABASE_URL="postgresql://postgres:postgres@localhost:5433/echo_memory" \
  -- /path/to/echo-mem/.venv/bin/python -m echo_memory.server
```

Check it connected: `claude mcp list` (look for `echo-memory ... Connected`). Start a
*new* Claude Code session afterward; sessions already running when you register won't
pick it up. Undo with `claude mcp remove echo-memory --scope user`.

For per-repo registration instead (a distinct memory scope for one project, or testing
without touching your global config), use a project-local `.mcp.json`:
```json
{
  "mcpServers": {
    "echo-memory": {
      "command": "/path/to/echo-mem/.venv/bin/python",
      "args": ["-m", "echo_memory.server"],
      "env": {
        "ECHO_MEMORY_USER_ID": "your-user-id",
        "ECHO_MEMORY_AGENT_ID": "claude-code",
        "ECHO_MEMORY_DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/echo_memory"
      }
    }
  }
}
```

Either way: each MCP client (Claude Code, Cursor, etc.) should point at its own instance
of this command with a distinct `ECHO_MEMORY_AGENT_ID`, sharing the same
`ECHO_MEMORY_DATABASE_URL` so `scope: "shared"` actually pools across them.

## CLI

```bash
echo-memory --scope solo why <fact_id>          # plain-language audit trail for one fact
echo-memory --scope solo export --out ./export  # markdown dump of a scope's memory
echo-memory --scope solo graph                  # terminal view of a scope's memory graph
echo-memory --scope solo graph --watch          # same, live-refreshing every 2s (--interval to change)
echo-memory --scope solo graph --html out.html  # self-contained interactive HTML snapshot, open in a browser
echo-memory status                              # v1a trial status: which Success Criteria are met so far
echo-memory trial check                         # criterion 6: the gate, and what's awaiting your judgement
echo-memory trial start                         # start the 3-week trial clock (--on YYYY-MM-DD to backdate)
echo-memory trial save "<what>" --from cursor   # log a recalled fact that saved re-explaining something
echo-memory trial log                           # every trial observation recorded so far
echo-memory dashboard --serve                   # one live page over every scope and project
echo-memory dashboard --out memory.html         # ...or a self-contained snapshot file
echo-memory --scope shared reattribute --list   # which session wrote which project's facts
echo-memory pending                             # memory files noticed but not yet in the graph
```

`--scope` defaults to `solo`. `fact_id` is whatever `query_memory` returned for that fact
(see the MCP tool contract); there's no raw `group_id` argument, `--scope` resolves it the
same way the server does. `status` checks both scopes at once, so it ignores `--scope`.

`status` reports against the design doc's v1a Success Criteria section: whether both
`solo` and `shared` scopes have real data, whether at least one `entity_resolved` audit
entry and one fact-mutation audit entry exist, plus criterion 6's tallies (below).
Criterion 3 (a real question where hybrid retrieval beats either signal alone) is the one
criterion still with nowhere to record it - `status` says so explicitly rather than
guessing.

### Criterion 6: the v1a -> v1b gate

Criterion 6 decides whether v1b starts: **3+ real instances where a recalled fact saved
re-explaining something to a different tool, at most 1 duplicate node, zero incorrectly
merged entities, over a trial capped at 3 weeks.** Every bar is a human judgement, which
is why they need recording somewhere rather than being remembered at the end. `trial`
records them; `status` and `trial check` report them. Nothing here judges anything on its
own.

```bash
echo-memory trial start --on 2026-08-21        # the clock, so the 3-week cap is measured
echo-memory trial check                        # the gate + everything awaiting judgement
echo-memory trial save "..." --from cursor     # --from is the tool that wrote the fact;
                                               # --into defaults to ECHO_MEMORY_AGENT_ID
```

`trial check` surfaces two kinds of open item, each printed with the exact command that
records a verdict on it:

- **Similar nodes that stayed separate** - one entity possibly split in two. Candidates
  are pairs scoring above the resolver's own `LOW_THRESHOLD`, i.e. pairs it would have
  flagged as ambiguous had they met in one call (see `ingestion/resolution.py`'s
  documented in-batch limitation). Judge with `trial dup <a> <b> "<why>"` or
  `trial not-dup <a> <b>`.
- **Entity resolutions not yet reviewed** - two entities possibly merged into one. Judge
  with `trial merge-ok <audit_id>` or `trial bad-merge <audit_id> "<why>"`. Exact-name
  matches are excluded by default as near-always correct; `--all` includes them.

A judged pair or reviewed resolution never comes back, and a second contradictory verdict
on the same one is refused rather than silently overwriting the first. A save where
`--from` and `--into` are the same tool is recorded but doesn't count toward the bar: the
criterion is specifically about a *different* tool not needing to be re-told.

`--html` writes a single HTML file with a draggable force-directed graph (nodes colored by
type, click one to jump to its facts) plus the full fact list grouped by source node. It's
a one-time snapshot, not live like `--watch` (`--watch` and `--html` are mutually
exclusive); open the file directly in a browser, no server needed. Node "type" values are
free text the calling agent chose, not a fixed enum, so colors are assigned deterministically
by hashing the type string, not a hardcoded palette per type name.

`graph` is a read-only observability aid, not a CEO-plan scope item: it prints each active
fact as `source --[relation]--> target` plus any nodes with no active facts, so you can see
what an agent has actually written without a separate `query_memory` call. `--watch` polls
the database on an interval and clears/reprints, so it reflects new writes as they land.

## Running tests

```bash
pytest                    # full suite
pytest -m "not eval"      # skip LLM-quality eval tests (slow, costs tokens)
pytest tests/unit/         # deterministic unit tests only
```

Per the CEO review's test-strategy split: deterministic logic (entity resolution
matching, RRF fusion, PPR correctness, audit log transactions) gets fast mocked unit
tests. The server has no LLM-judgment code path of its own to eval-test (extraction,
entity-resolution confirmation, and `causal_hint` classification all happen in the
calling agent, see the design doc's MCP tool contract); the `eval` marker (`pytest -m
eval`) is reserved for future retrieval-quality evals, not in use yet.

`tests/integration/` applies real migrations against `ECHO_MEMORY_DATABASE_URL` (its
`migrated_db` fixture runs `alembic upgrade head` before each test and `downgrade base`
after) and checks the resulting schema; it self-skips if that database isn't reachable.
CI runs it too now (see `.github/workflows/ci.yml`), against its own throwaway database.

**Point it at the `db-test` service, not `db`**, if you also have `echo-memory`
registered as a real MCP server (e.g. via `claude mcp add`) pointing at `db`'s database.
Running the suite against a database a real client is also using will downgrade that
schema to nothing mid-test-run, from underneath whatever's actually using it - this
happened once, don't repeat it.

```bash
docker compose --profile test up -d db-test   # separate container, separate volume, port 5434
export ECHO_MEMORY_DATABASE_URL="postgresql://postgres:postgres@localhost:5434/echo_memory"
pytest
```

## Database migrations

```bash
alembic revision -m "short description"   # create a new migration
alembic upgrade head                       # apply
alembic downgrade -1                       # roll back one step
```

## Common issues

- **`alembic upgrade head` fails with "role postgres does not exist" even though
  `docker compose up` succeeded.** Something else on your machine (a native Postgres
  install, a homebrew service, an SSH tunnel) is already listening on 5432, and your
  connection is silently hitting that instead of the container. Check with
  `lsof -nP -iTCP:5432 -sTCP:LISTEN`. This is exactly why `docker-compose.yml` maps
  the container to host port 5433, not 5432; if you changed that back, change it back
  again, or point `ECHO_MEMORY_DATABASE_URL` at whatever port you actually chose.


## Projects

Every fact records the project it was written from, alongside the agent that
wrote it (`agent_id`) and the session (`provenance.session_id`). The project is
resolved server-side from the process's working directory - the repo root's
name, falling back to the directory's name - and is **never** passed in by the
calling agent, for the same reason `group_id` isn't: a value an agent types is
a value an agent types inconsistently, and "eigen" / "Eigon" / "eigen-backend"
across three calls would defeat the grouping entirely.

This works with no per-project setup because each session starts its own MCP
server process whose cwd is the project directory. `ECHO_MEMORY_PROJECT`
overrides it for callers where cwd means nothing: the direct Python client
inside a long-running service, a container whose cwd is `/app`, a chatbot
serving many tenants from one process.

**Project is not part of `group_id`.** `group_id` is the tenancy boundary;
making it per-project would partition memory per repo and destroy the
cross-project recall the system exists for. Project is an attribute *within* a
scope, and it lives on the edge rather than the node, because a fact is
authored in one project at one moment while a node like `Postgres` can be
referenced from several. A node's projects are derived from its edges.

Facts written before migration `0003` are marked `unknown`. Session ids are
per-install, so the migration doesn't guess:

```bash
echo-memory --scope shared reattribute --list                        # see what's unattributed
echo-memory --scope shared reattribute --session <id> --project eigen
```

## Automatic capture

`write_episode` fires when a model decides to call it. Measured over the first
two days of the v1a trial that was 4 times, while the agent's own file-based
memory wrote 7 files in the same window because a hook fired deterministically.
The capture path already existed; it just wasn't wired to Echo Memory.

`scripts/capture-memory-hook.sh` closes that. Register it as a `PostToolUse`
hook on `Write|Edit` in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "ECHO_MEMORY_USER_ID=you ECHO_MEMORY_AGENT_ID=claude-code ECHO_MEMORY_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/echo_memory ECHO_MEMORY_BIN=/path/to/echo-mem/.venv/bin/echo-memory /path/to/echo-mem/scripts/capture-memory-hook.sh"
          }
        ]
      }
    ]
  }
}
```

The hook **queues; it does not extract**. Turning prose into entities and facts
needs a model, and the server never calls one (design doc, MCP tool contract,
architecture pivot). So `query_memory` returns a `pending_ingest` field at
session start listing what the graph hasn't heard about, the agent reads those
files and calls `write_episode`, and then:

```bash
echo-memory pending                    # what's outstanding
echo-memory pending --done <path>...   # close them once they're in the graph
```

The queue stores a digest, not the file's content: it tracks what still needs
reading, and a second copy of the memory would be one more place for the same
fact to disagree with itself. Editing a memory file reopens its entry, because
the file now says something the graph hasn't heard.

The hook never blocks or fails a tool call - a memory-capture side effect has
no business breaking the edit that triggered it - so every path exits 0.

## Dashboard

```bash
echo-memory dashboard --serve          # http://127.0.0.1:8787, regenerated per reload
echo-memory dashboard --out memory.html
```

One page over both scopes and every project. Nodes are coloured by the project
that talks about them most, filtered by the project chips and the scope
segment, searchable by fact text.

Clicking a **node** shows the facts it takes part in, active and superseded,
plus how it resolved during ingestion. Clicking a **link** shows what that one
fact carries:

| | |
|---|---|
| **what** | the fact text, its `relation_type`, and the confidence the agent stated |
| **when** | `t_valid`, and `t_invalid` if it has since been superseded |
| **who** | the agent that wrote it and the session it wrote it in |
| **where** | the project |
| **why** | the audit trail: created, superseded from what to what, and the entity-resolution rationale for the nodes at either end |

Only active facts draw a link, since a superseded fact is a relationship the
graph no longer asserts; it stays reachable from its node's list and from its
own history. `--serve` regenerates on every request, because a snapshot is
stale the moment the next episode lands. It binds to localhost only: the page
is every fact you have ever recorded, across every project.
