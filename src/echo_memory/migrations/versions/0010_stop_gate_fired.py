"""remember which sessions the stop gate has already held open

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-02

The gate shipped relying on Claude Code's `stop_hook_active` flag to fire at
most once per session. On 2026-09-02 an eigen session reported "Ran 5 stop
hooks" and spent 27 minutes unable to satisfy any of them, because that flag is
set only while a session is *continuing* from a stop hook - once the agent
answers and stops again, it is a fresh stop with the flag clear.

So the bound has to be recorded rather than inferred. One row per session that
has been gated; a session already in this table is never gated again, whatever
the flag says and however many times Stop fires.

This is the bound that matters most, because the gate cannot verify that the
session it is holding open is *able* to comply: write_episode may be absent
from that session's tool list and the CLI may not be on its PATH, in which case
blocking achieves nothing and costs the user real time. One nudge, then never
again, is the only safe shape for a hook that can be unsatisfiable."""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.stop_gate_fired (
            session_id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            n_files INTEGER NOT NULL DEFAULT 0,
            at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.stop_gate_fired")
