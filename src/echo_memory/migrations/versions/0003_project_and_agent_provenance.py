"""project and agent_id on every fact, plus the pending-ingest queue

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-23

Until now a fact recorded *what*, *when* (t_valid/t_invalid) and *which
session* (provenance.session_id), but not which project it came from or which
agent wrote it. Two consequences, both hit in real use:

- Every project's facts sat in one undifferentiated `shared` scope, so there
  was no way to view memory per project, and no way to tell that a
  similar-looking node pair belongs to two unrelated codebases.
- In `shared` scope the writing agent is unrecoverable. `group_id` encodes the
  agent for `solo` (user:X:agent:Y) but `shared` is user:X:shared by
  construction, so "who wrote this" had no answer at all.

`project` deliberately does NOT become part of `group_id`. group_id is the
tenancy/sharing boundary (see the design doc's Configuration section); making
it per-project would partition memory per repo and destroy the cross-project
recall this whole system exists for. Project is an attribute *within* a scope.

Both live as top-level edge properties rather than inside the existing
`provenance` map, because AGE indexes a top-level property cleanly
(`properties ->> '"project"'::agtype`) and a nested one does not.

They go on the EDGE, not the node, and that's a real modelling choice: a fact
is authored in one project at one moment, but a node like "Postgres" can
legitimately be referenced from several. A node's projects are therefore
derived from its edges, never stored.

BACKFILL: existing edges get 'unknown' rather than a guess. Session ids are
per-install, so a migration can't map them to projects without hardcoding one
person's history into an open-source repo. `echo-memory reattribute --session
<id> --project <name>` does that for an operator's own historical data, and
is documented in DEVELOPMENT.md.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

GRAPH = "echo_memory"
UNKNOWN = "unknown"


def prop(key: str) -> str:
    return f"(properties ->> '\"{key}\"'::agtype)"


def upgrade() -> None:
    op.execute("LOAD 'age'")
    op.execute('SET search_path = ag_catalog, "$user", public')

    # Every existing fact gets the properties so the indexes below are total
    # and queries never have to special-case a missing key.
    op.execute(f"""
        SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->()
            SET e.project = '{UNKNOWN}', e.agent_id = '{UNKNOWN}'
        $$) AS (result agtype)
    """)

    op.execute(
        f'CREATE INDEX fact_group_project_idx ON {GRAPH}."FACT" '
        f'(({prop("group_id")}), ({prop("project")}))'
    )
    op.execute(
        f'CREATE INDEX fact_group_agent_idx ON {GRAPH}."FACT" '
        f'(({prop("group_id")}), ({prop("agent_id")}))'
    )

    # The capture queue (see cli/ingest.py). A hook records that a memory file
    # changed; extraction into entities/facts stays with the calling agent,
    # since the server never calls an LLM (design doc, MCP tool contract
    # architecture pivot). Digest, not content: this table tracks what still
    # needs reading, it is not a second copy of the memory itself.
    op.execute("""
        CREATE TABLE public.pending_ingest (
            path TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            digest TEXT NOT NULL,
            noticed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            ingested_at TIMESTAMPTZ
        )
    """)
    op.execute(
        "CREATE INDEX pending_ingest_open_idx ON public.pending_ingest (project) "
        "WHERE ingested_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.pending_ingest")
    op.execute("LOAD 'age'")
    op.execute('SET search_path = ag_catalog, "$user", public')
    op.execute(f'DROP INDEX IF EXISTS {GRAPH}.fact_group_agent_idx')
    op.execute(f'DROP INDEX IF EXISTS {GRAPH}.fact_group_project_idx')
    op.execute(f"""
        SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->()
            REMOVE e.project, e.agent_id
        $$) AS (result agtype)
    """)
