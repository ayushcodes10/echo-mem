"""record that a session did work, so a session that recorded nothing is visible

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-09

The Stop gate holds a session open until the memory files it wrote are in the
graph. That closed the case it was built for and left the larger one open: a
session that writes no memory file is never prompted at all, because the gate
counts queued files and zero queued files reads as nothing owed.

Measured, twice. Between 2026-08-28 and 2026-08-31 Claude Code merged eight PRs
of work on this project and called write_episode zero times. On 2026-09-09
Codex was asked to write a deployment runbook, told that another tool had spent
two days building the service, made twenty query_memory calls, and reported
honestly that memory returned nothing useful - because the constraints from
those two days lived in commit messages and READMEs and had never been written
with write_episode. The Stop gate was installed and firing for both.

A hook can only fire on an artefact. The artefact here is not a file, it is the
work itself, so this table records the one thing that was always observable and
never recorded: that a session edited things. Paired with the audit log, which
already knows which session wrote which fact, "worked hard and recorded
nothing" becomes a question the gate can ask.

Counts only. No paths, no content, no query text - the same line migration 0008
drew for reads. What is stored is a number per session, which is enough to ask
the question and not enough to reconstruct anything.
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.session_activity (
            session_id  TEXT PRIMARY KEY,
            project     TEXT NOT NULL,
            n_edits     INTEGER NOT NULL DEFAULT 0,
            first_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # The gate asks "this project, this session", and nothing else ever will.
    op.execute(
        "CREATE INDEX session_activity_project_idx ON public.session_activity (project, last_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.session_activity")
