"""record that a read happened, and what it cost

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-01

Writes have been counted since the beginning (group_state.write_episode_count).
Reads were never counted at all, so nothing could answer the question the whole
product rests on: does recall earn what it costs?

The cost is real and continuous. The UserPromptSubmit hook injects roughly 330
tokens into every prompt whether or not anything retrieved turns out to matter -
measured 2026-09-01 at ~1340 characters across three sample prompts. Over a
200-prompt day that is ~66k input tokens spent on memory. Nothing measured it,
and criterion 6 could not: it counts an agent's self-reported saves, not a cost.

One row per read rather than a counter on group_state, because the useful form
of this is a rate over a window - "recall fired 340 times this week for 110k
tokens, and produced 12 saves" - and a running total cannot be windowed after
the fact. The table is append-only and narrow; a read costs one INSERT.

Deliberately does not store the query or the facts returned. This is about
volume and cost, and a log of everything anyone ever asked memory is a different
artifact with different privacy implications than a count of how often they did.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.read_event (
            id BIGSERIAL PRIMARY KEY,
            group_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            n_facts INTEGER NOT NULL DEFAULT 0,
            injected_chars INTEGER NOT NULL DEFAULT 0,
            at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX read_event_at_idx ON public.read_event (at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.read_event")
