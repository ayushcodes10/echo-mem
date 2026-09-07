"""backfill facts whose agent_id key is absent entirely

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-07

Migration 0003 set `project` and `agent_id` on every fact that existed when it
ran, and 0007 relabelled the resulting 'unknown' agents as 'claude-code'. Both
were correct about the data in front of them and both missed this case, because
the facts it covers did not exist yet.

They were written afterwards, by code that predated `agent_id`. A Claude Code
MCP server is a long-lived stdio process: it imports the package once, when the
client spawns it, and keeps that code for its whole life. An editable install
does not help - the import already happened. One such process (pid 53784,
started 2026-08-22 17:47, before `agent_id` shipped on 2026-08-23) was still
writing facts on 2026-09-03. Thirty facts in the author's own store came from
it and its siblings.

Apache AGE drops a property whose value is null at CREATE time, so these facts
carry no `agent_id` key at all rather than an explicit null. That is precisely
why 0007's `WHERE e.agent_id = 'unknown'` did not match them, and why a check
for the literal string 'unknown' will not find them in anyone else's database
either. `IS NULL` matches both an absent key and a null one, which is what this
wants.

The value written is 'unknown', NOT 'claude-code'. 0007 could name claude-code
honestly because it reasoned about a specific store in which no other client
had ever been configured. This migration runs on installs whose history nobody
here has seen, and by 2026-08-29 `adopt` was giving Codex, Cursor and Claude
Desktop their own agent ids, so a fact from this window genuinely might not be
claude-code's. 'unknown' is also the safe direction for the one measurement
that reads this field: `record_recall_save` rejects UNKNOWN_AGENT outright,
whereas any concrete name would let these facts evidence a cross-tool save that
nobody can substantiate.

The downgrade is a no-op for the same reason 0007's is: nothing distinguishes a
row this migration touched from one that always said 'unknown'.
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

GRAPH = "echo_memory"
UNKNOWN = "unknown"


def upgrade() -> None:
    # AGE has to be loaded and ag_catalog put on the search_path in every
    # migration that touches the graph; Alembic's connection does not inherit
    # what the application sets. Omitting these is what made 0007 fail the
    # first time it met real data, since CI only ever migrates an empty
    # database and the cypher body had never executed.
    op.execute("LOAD 'age'")
    op.execute('SET search_path = ag_catalog, "$user", public')
    op.execute(f"""
        SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->()
            WHERE e.agent_id IS NULL
            SET e.agent_id = '{UNKNOWN}'
            RETURN count(e)
        $$) AS (n agtype)
    """)


def downgrade() -> None:
    """Deliberately a no-op. Removing agent_id from every fact that says
    'unknown' would strip it from facts 0003 backfilled too, which this
    migration never touched."""
