"""say which project and session a read happened in

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-02

read_event shipped one day ago recording group_id, kind, n_facts and
injected_chars. group_id is 'user:ayush:shared' for every Claude Code session
in every project, so the table could count reads but could not attribute one.

That gap surfaced immediately. Asked "did the eigen sessions read memory?",
the table had no answer: 12 rows, all identically labelled. The write side has
carried project since 0003 and the read side did not, so reads and writes could
not be compared along the one dimension that matters for deciding whether
recall earns its cost in a given repo.

session_id comes with it. A read and the write it eventually produced belong to
the same session, and without it "recall fired 40 times and produced one save"
cannot be narrowed to whether that was one session or forty.

Both nullable: the hook may be running against an older CLI mid-upgrade, and a
read that records without attribution is still worth more than an exception on
the prompt path.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.read_event ADD COLUMN project TEXT")
    op.execute("ALTER TABLE public.read_event ADD COLUMN session_id TEXT")
    # Reads are queried as "this project, recent first" on every dashboard and
    # health render; without project leading the index that is a full scan.
    op.execute("CREATE INDEX read_event_project_at_idx ON public.read_event (project, at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS read_event_project_at_idx")
    op.execute("ALTER TABLE public.read_event DROP COLUMN IF EXISTS session_id")
    op.execute("ALTER TABLE public.read_event DROP COLUMN IF EXISTS project")
