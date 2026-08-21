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
```

`--scope` defaults to `solo`. `fact_id` is whatever `query_memory` returned for that fact
(see the MCP tool contract); there's no raw `group_id` argument, `--scope` resolves it the
same way the server does.

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

`tests/integration/` applies real migrations against `ECHO_MEMORY_DATABASE_URL` and
checks the resulting schema; it self-skips if that database isn't reachable, so it
needs `docker compose up -d` and a real `ECHO_MEMORY_DATABASE_URL` to actually run.
CI doesn't run it yet (see `TODOS.md`).

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
