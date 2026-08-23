"""where a queued document came from, and whether first-run discovery has run

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-23

A fresh install starts empty while the machine it runs on is already full of
recorded work: per-project memory files, company-memory digests, gstack
learnings, CLAUDE.md files. None of that reached the graph, so a store
initialised today knew nothing about work done yesterday and the user got to
re-explain all of it.

`bootstrap_state` is a singleton marking that discovery has run, so it happens
once rather than on every session start. `pending_ingest.source` records which
kind of reference a queued document came from, because "read this file and
extract facts" means something different for a hand-written memory note than
for a JSONL log of skill learnings, and the agent working the queue needs to
know which it's holding.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.pending_ingest ADD COLUMN source TEXT NOT NULL DEFAULT 'file'")

    op.execute("""
        CREATE TABLE public.bootstrap_state (
            id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
            discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            n_found INTEGER NOT NULL DEFAULT 0
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.bootstrap_state")
    op.execute("ALTER TABLE public.pending_ingest DROP COLUMN IF EXISTS source")
