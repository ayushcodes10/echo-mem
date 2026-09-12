"""keep every trial run, not just the current one

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-12

trial_run held exactly one row - `id boolean PRIMARY KEY CHECK (id)` - so there
was no way to start a second trial except by overwriting the first. Starting
over meant destroying the record of what the first one measured, which is the
one thing a trial is for.

That matters now because the first run has to be closed. It ran from
2026-08-21 to 2026-09-11 over an instrument that was broken for its whole
duration: every bad merge it recorded came from a caller-supplied node id taken
on trust, its one duplicate came from a claim of novelty that skipped the exact
match, and its only recorded duplicate before that was two scopes rather than
two entities. All four holes are closed. The observations are accurate records
of what happened and they measure a system that no longer exists.

So runs become history. At most one is open at a time, which the partial unique
index enforces rather than trusts.
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.trial_run DROP CONSTRAINT IF EXISTS trial_run_pkey")
    op.execute("ALTER TABLE public.trial_run DROP CONSTRAINT IF EXISTS trial_run_id_check")
    op.execute("ALTER TABLE public.trial_run DROP COLUMN IF EXISTS id")
    op.execute(
        "ALTER TABLE public.trial_run "
        "ADD COLUMN id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
    )
    # Null while the run is open. Closing a run is a decision, so it carries a
    # reason for the same purpose a retraction does: the record has to show why
    # a measurement stopped counting, or stopping counting is indistinguishable
    # from editing the result.
    op.execute("ALTER TABLE public.trial_run ADD COLUMN IF NOT EXISTS ended_on DATE")
    op.execute("ALTER TABLE public.trial_run ADD COLUMN IF NOT EXISTS ended_reason TEXT")
    op.execute("""
        ALTER TABLE public.trial_run
            ADD CONSTRAINT trial_run_close_has_a_reason
            CHECK (ended_on IS NULL OR ended_reason IS NOT NULL)
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS trial_run_one_open_idx "
        "ON public.trial_run ((true)) WHERE ended_on IS NULL"
    )


def downgrade() -> None:
    # The old shape holds exactly one run, so going back cannot keep the
    # closed ones - `id boolean PRIMARY KEY` has room for one row and every row
    # would take the same key. The open run survives because it is the one a
    # tally is taken over; the history is lost, which is what downgrading to a
    # schema that cannot hold history means.
    op.execute("DELETE FROM public.trial_run WHERE ended_on IS NOT NULL")
    op.execute("DROP INDEX IF EXISTS public.trial_run_one_open_idx")
    op.execute(
        "ALTER TABLE public.trial_run DROP CONSTRAINT IF EXISTS trial_run_close_has_a_reason"
    )
    op.execute("ALTER TABLE public.trial_run DROP COLUMN IF EXISTS ended_reason")
    op.execute("ALTER TABLE public.trial_run DROP COLUMN IF EXISTS ended_on")
    op.execute("ALTER TABLE public.trial_run DROP COLUMN IF EXISTS id")
    op.execute("ALTER TABLE public.trial_run ADD COLUMN id BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE public.trial_run ADD PRIMARY KEY (id)")
    op.execute("ALTER TABLE public.trial_run ADD CONSTRAINT trial_run_id_check CHECK (id)")
