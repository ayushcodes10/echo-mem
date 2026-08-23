"""guard recall saves against accidental double-counting

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-23

Criterion 6's recall-save bar is exactly three. `trial_observation` already
guards duplicate node-pair verdicts and duplicate merge reviews, but nothing
guarded recall saves, because until now the only way to record one was a human
typing a CLI command. An MCP tool changes that: an agent that retries after a
timeout, or logs twice in one enthusiastic turn, moves the counter. Two
accidents plus one real save reads as gate met.

The uniqueness key is (group_id, written_by, note). Same tool, same sentence,
same scope is a retry rather than a second occasion; two genuinely different
saves from the same tool still both count, because the note differs. This is
the same idempotency shape `capture.notice` already uses for an unchanged file.

Partial on `kind = 'recall_save'` so the other observation kinds keep their
existing behaviour: a second, contradictory verdict on a node pair or a merge
review must still raise rather than silently no-op, because there the conflict
is a real disagreement worth surfacing.

`written_by` is NOT NULL-guarded here at the application layer instead of the
schema: NULLs are distinct under a unique index, so a recall save with no
written_by would slip past this guard entirely. `observations.record` therefore
rejects a recall save that is missing either tool - which is also what criterion
6's "to a different tool" clause needs in order to mean anything.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX trial_observation_recall_save_idx
        ON public.trial_observation (group_id, written_by, note)
        WHERE kind = 'recall_save'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.trial_observation_recall_save_idx")
