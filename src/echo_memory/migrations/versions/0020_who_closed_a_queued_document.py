"""record which session closed a queued document

The Stop gate's conversion rate - how often a firing produced captured
knowledge, as opposed to how often it fired - cannot be computed without this.

A firing resolves in one of two ways. The session writes the facts, which the
audit log already attributes by session_id. Or the session finds the content
already recorded and closes the document, which the gate's own instruction asks
for in exactly that case - and which `pending_ingest` recorded with a timestamp
and nothing else.

Without an author on the closure the metric has only bad options: ignore
closures, and a session that did the right thing scores as a failure; or count
any closure after the firing, and every historical firing matches something.
Both were tried on 2026-09-13 and produced 1 of 8 and 8 of 8 from the same
data.

Nullable and not backfilled. Closures made before this migration have no
recorded author and there is no way to recover one; guessing from the timestamp
is how the second wrong number was produced.

Revision ID: 0020
Revises: 0019
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.pending_ingest ADD COLUMN IF NOT EXISTS "
        "ingested_by_session TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.pending_ingest DROP COLUMN IF EXISTS ingested_by_session"
    )
