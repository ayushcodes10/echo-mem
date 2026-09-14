"""let two judges label the same pair, and keep both

The independent evaluation stored one relevance label per (question, fact),
which is what makes it blind: there is nowhere for a configuration's identity
to enter. It also meant a second judge overwrote the first.

That hid the largest source of uncertainty in the result. One judging pass over
these pools marked 5 facts relevant; a second marked 23. The configurations are
separated by less than that spread, so which pass is used matters more than
which retriever is used - and the first pass had already been deleted by the
time anyone wanted to compare them, which is a loss of evidence caused by
tidying up.

The key now carries the judge. Both label sets coexist, scoring can be run
against either, and agreement between them is computable rather than asserted.

Revision ID: 0023
Revises: 0022
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows have judged_by set by the writer; anything older is
    # attributed to 'unknown' rather than dropped, because a label nobody can
    # attribute is still a label somebody made.
    op.execute(
        "UPDATE public.eval_judgement SET judged_by = 'unknown' WHERE judged_by IS NULL"
    )
    op.execute("ALTER TABLE public.eval_judgement ALTER COLUMN judged_by SET NOT NULL")
    op.execute(
        "ALTER TABLE public.eval_judgement DROP CONSTRAINT IF EXISTS eval_judgement_pkey"
    )
    op.execute(
        "ALTER TABLE public.eval_judgement "
        "ADD PRIMARY KEY (question_id, edge_id, judged_by)"
    )


def downgrade() -> None:
    # Collapsing back to one label per pair has to choose a judge, and choosing
    # silently is how the first pass was lost. Keep the earliest.
    op.execute(
        """DELETE FROM public.eval_judgement a
           USING public.eval_judgement b
           WHERE a.question_id = b.question_id AND a.edge_id = b.edge_id
             AND a.judged_at > b.judged_at"""
    )
    op.execute(
        "ALTER TABLE public.eval_judgement DROP CONSTRAINT IF EXISTS eval_judgement_pkey"
    )
    op.execute(
        "ALTER TABLE public.eval_judgement ADD PRIMARY KEY (question_id, edge_id)"
    )
    op.execute("ALTER TABLE public.eval_judgement ALTER COLUMN judged_by DROP NOT NULL")
