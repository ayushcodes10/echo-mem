# Local Development

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- An embedding API key (provider TBD; see the design doc's Open Questions)

## First-time setup

```bash
git clone git@github.com:ayushcodes10/echo-mem.git
cd echo-mem

# Start Postgres with pgvector + Apache AGE (built from source on top of
# pgvector/pgvector:pg16, not the apache/age image — see docker/postgres.Dockerfile
# and the design doc's Foundational spike section for why)
docker compose up -d

# Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# edit .env: set ECHO_MEMORY_USER_ID, ECHO_MEMORY_AGENT_ID, ECHO_MEMORY_DATABASE_URL,
# and your embedding provider's API key

# Apply migrations
alembic upgrade head
```

## Running the MCP server locally

Not built yet (PR5 in the design doc's PR Plan). Once it exists:

```bash
python -m echo_memory.server
```

Point your MCP client (Claude Code's `.mcp.json`, Cursor's MCP config, etc.) at this
process. Each client should run its own instance with a distinct `ECHO_MEMORY_AGENT_ID`;
see the design doc's "Configuration" section for how `scope: "solo" | "shared"`
resolves per agent.

## Running tests

```bash
pytest                    # full suite
pytest -m "not eval"      # skip LLM-quality eval tests (slow, costs tokens)
pytest tests/unit/         # deterministic unit tests only
```

Per the CEO review's test-strategy split: deterministic logic (entity resolution
matching, RRF fusion, PPR correctness, audit log transactions) gets fast mocked unit
tests. LLM-quality judgment (causal_hint classification, entity-resolution's fuzzy
confirm pass) is only measured by the eval suite (`pytest -m eval`), never mocked.

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
