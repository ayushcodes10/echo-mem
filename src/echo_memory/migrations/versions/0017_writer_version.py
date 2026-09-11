"""record which version of the package wrote an audit entry

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-11

An MCP stdio server is started once by the client and lives for the whole
session, so it holds the code it imported at spawn. Upgrading the package does
not change what that process runs, and an editable install does not either -
the module objects are already in memory. Nothing anywhere says so.

That has now produced two separate data bugs in this store. A server spawned
before agent_id existed kept writing facts with no author for sixteen days, 30
of them, and 27 are unrecoverable. A server spawned before project reached the
edge properties wrote seven facts with no project, six of them on the day it
was found. In both cases the code on disk was correct, the tests passed, and
the running process was writing through the version it had.

There is no way to detect that from outside without asking what actually wrote
something. This column is that question: `health` compares the newest entry's
version against the installed one and says "restart your client" rather than
leaving the next person to find it in the data six weeks later.

On audit_entry rather than on the facts themselves. Every mutation writes an
audit row, so the coverage is the same, and it costs one column on a log
instead of a property on every edge in the graph.
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no backfill. Rows written before this existed were written
    # by a version nobody recorded, and inventing one would make the staleness
    # check answer confidently about the very period it cannot see.
    op.execute("ALTER TABLE public.audit_entry ADD COLUMN IF NOT EXISTS writer_version TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE public.audit_entry DROP COLUMN IF EXISTS writer_version")
