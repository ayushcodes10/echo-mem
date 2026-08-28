"""backfill agent_id 'unknown' to 'claude-code'

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-28

Migration 0003 added `agent_id` to every fact and backfilled the rows that
predated it with the literal 'unknown', which was the honest choice at the time:
the data genuinely did not record who wrote them.

It became a correctness problem once `record_recall_save` shipped. Criterion 6
counts a save only when `written_by != recalled_by`, and 'unknown' compares
unequal to 'claude-code'. So three saves citing backfilled facts would satisfy
the cross-tool gate while being exactly the same-tool recall the gate exists to
exclude - and the temptation to accept them is highest at the moment the number
finally moves.

Every one of these facts was in fact written by claude-code: it was the only
client that ever wrote to this store, and until 2026-08-28 `install` handed the
same agent id to every client it configured, so no other value could have been
recorded. Naming the writer is more accurate than the placeholder, and it closes
the hole in the data rather than guarding against it in three separate callers.

The downgrade is LOSSY. Once these rows say 'claude-code' there is no marker
distinguishing them from facts genuinely written under that id, so the reverse
migration cannot restore 'unknown' and does not pretend to.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

GRAPH = "echo_memory"


def upgrade() -> None:
    op.execute(f"""
        SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->()
            WHERE e.agent_id = 'unknown'
            SET e.agent_id = 'claude-code'
            RETURN count(e)
        $$) AS (n agtype)
    """)


def downgrade() -> None:
    """Deliberately a no-op. See the module docstring: the information needed to
    reverse this was destroyed by the upgrade, and silently relabelling every
    claude-code fact as 'unknown' would corrupt facts this migration never
    touched."""
