# Local Development

> **Status:** this describes the target setup once PR1 (repo scaffold, Docker Compose,
> migrations, schema) lands — see [`docs/designs/`](designs/) for the build plan. Update
> this doc in the same PR that makes each step real; a setup guide that doesn't match
> what actually exists is worse than none.

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- An embedding API key (provider TBD — see the design doc's Open Questions)

## First-time setup

```bash
git clone git@github.com:ayushcodes10/echo-mem.git
cd echo-mem

# Start Postgres with pgvector (and, from v1b onward, Apache AGE)
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

```bash
python -m echo_memory.server
```

Point your MCP client (Claude Code's `.mcp.json`, Cursor's MCP config, etc.) at this
process. Each client should run its own instance with a distinct `ECHO_MEMORY_AGENT_ID`
— see the design doc's "Configuration" section for how `scope: "solo" | "shared"`
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

## Database migrations

```bash
alembic revision -m "short description"   # create a new migration
alembic upgrade head                       # apply
alembic downgrade -1                       # roll back one step
```

## Common issues

_(fill in as they come up — this section starts empty on purpose)_
