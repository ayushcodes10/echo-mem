"""record which tool performed a read

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-09

Writes have said who made them since migration 0003. Reads never have, and the
gap only became visible once more than one tool was actually reading.

On 2026-09-09, with Claude Code, Codex and Claude Desktop all connected, the
question "which of them is actually using memory" had no answer in the data.
`read_event` carries `group_id`, and for the shared scope that is
`user:<id>:shared` for every tool alike, so a hundred reads and one read look
identical no matter who did them. `echo-memory health` reports read volume and
cannot say whose.

That matters beyond curiosity. The product's claim is cross-tool recall, and
the read side is half of it: a fact written by one tool is worth nothing until
a different tool reads it. Without this column there is no way to show that
happening, only to assert it.

Nullable, and deliberately not backfilled. Every existing row genuinely
predates the column and there is no evidence of who made those reads - the
sessions are gone. Guessing 'claude-code' because it was the likeliest would
put a number in the dashboard that nobody could defend, which is the mistake
migration 0011's docstring exists to warn about.
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.read_event ADD COLUMN agent_id TEXT")
    # Every question asked of this column is "who read, in this group, lately",
    # so the index leads with the two that narrow hardest.
    op.execute(
        "CREATE INDEX read_event_group_agent_idx "
        "ON public.read_event (group_id, agent_id, at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS read_event_group_agent_idx")
    op.execute("ALTER TABLE public.read_event DROP COLUMN IF EXISTS agent_id")
