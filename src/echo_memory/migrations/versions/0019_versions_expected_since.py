"""record the moment a writer's version became expected

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-12

Migration 0017 added audit_entry.writer_version so a stale MCP server could be
detected, and health's check skipped rows where it is null - "rows written
before this existed were written by a version nobody recorded, and inventing
one would make the check answer confidently about the very period it cannot
see."

That reasoning was right and the check it produced is blind to the case that
matters. A server old enough to predate the column writes null forever, so the
newest row keeps saying "no version recorded" and the check keeps skipping it.
The server that caused 30 authorless facts would have been invisible to the
detector built to find it.

A null is only uninformative before the column existed. After that, a write
with no version is proof the writer predates it. This records which side of
that line a row falls on - a single timestamp, written when this migration
runs, which is by definition the moment after which every current writer
stamps its version.
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.schema_moment (
            name        TEXT PRIMARY KEY,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # now(), not a hardcoded date: the moment that matters is when this
    # database gained the column, which differs per install.
    op.execute("""
        INSERT INTO public.schema_moment (name) VALUES ('writer_version_expected')
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM public.schema_moment WHERE name = 'writer_version_expected'")
