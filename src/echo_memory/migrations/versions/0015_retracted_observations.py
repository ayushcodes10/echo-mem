"""let a trial observation be retracted rather than deleted

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-11

The trial's only recorded duplicate turned out to be 'Ayush' in solo and
'Ayush' in shared - two scopes, which are separate namespaces by construction,
so correct scoping rather than one entity split in two. The judgement was made
in good faith on ids that nothing validated at the time.

There was no way to say so. The row could be deleted, which edits the record of
a trial and leaves nobody able to see that a mistake was made, or it could
stand, which leaves the exit gate reading a tally that is wrong. Neither is
what an instrument should offer.

Retraction is the third option and the honest one: the row stays, the reason
stays with it, and the counts stop including it. Recorded as a timestamp rather
than a boolean so "when did this stop counting" is answerable, which matters
when the number it feeds is a gate.
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.trial_observation ADD COLUMN IF NOT EXISTS retracted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE public.trial_observation ADD COLUMN IF NOT EXISTS retracted_reason TEXT")
    # A retraction with no reason is a deletion wearing a different name.
    op.execute("""
        ALTER TABLE public.trial_observation
            ADD CONSTRAINT trial_observation_retraction_has_a_reason
            CHECK (retracted_at IS NULL OR retracted_reason IS NOT NULL)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE public.trial_observation
            DROP CONSTRAINT IF EXISTS trial_observation_retraction_has_a_reason
    """)
    op.execute("ALTER TABLE public.trial_observation DROP COLUMN IF EXISTS retracted_reason")
    op.execute("ALTER TABLE public.trial_observation DROP COLUMN IF EXISTS retracted_at")
