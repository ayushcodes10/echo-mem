"""questions written before retrieval, and relevance judged per fact

The evaluation harness in echo_memory/eval/retrieval.py derives every query
from the answer it is looking for. That makes its labels free and its absolute
scores meaningless, and - as two review rounds established - it also makes the
DIFFERENCE between configurations untrustworthy, because a biased task can
change which one wins. The harness stays, as a regression signal. It cannot
settle which configuration should ship.

This is the other kind of evaluation. Three tables, shaped so that the
independence claims are structural rather than promises:

  eval_question   the question, and the retriever commit frozen at the moment
                  it was written. A question recorded before anything was
                  retrieved cannot have been fitted to a result.

  eval_run        one configuration scored against one question, storing the
                  ordered fact ids it returned. Written after judging opens,
                  never before: the judge must not see which configuration
                  produced a candidate.

  eval_judgement  relevance for a (question, fact) PAIR - not for a
                  (question, configuration) pair. A fact useful for a question
                  is useful whoever surfaced it, so one label serves every
                  configuration and more than one fact may be right. This is
                  what makes the judging blind and multi-label at the same
                  time: there is nowhere for a configuration's identity to
                  enter the label.

What this design cannot fix is pooling bias. A fact that no configuration
returned is never judged, so recall is recall over the pooled relevant set and
not over the store. That is stated wherever the number is printed.

Revision ID: 0022
Revises: 0021
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.eval_question (
            id            SERIAL PRIMARY KEY,
            group_id      TEXT NOT NULL,
            text          TEXT NOT NULL,
            subject       TEXT,
            -- The commit the retriever was frozen at when this question was
            -- written. A question and a score from different code are two
            -- measurements, and the paper has already published one pair of
            -- those by accident.
            retriever_sha TEXT,
            author        TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            -- Set when judging opens. Nothing may be retrieved for a question
            -- before this, which is the ordering the independence rests on.
            opened_at     TIMESTAMPTZ,
            UNIQUE (group_id, text)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.eval_run (
            question_id   INTEGER NOT NULL REFERENCES public.eval_question(id)
                              ON DELETE CASCADE,
            configuration TEXT NOT NULL,
            returned      TEXT[] NOT NULL,
            retriever_sha TEXT,
            ran_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (question_id, configuration)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.eval_judgement (
            question_id INTEGER NOT NULL REFERENCES public.eval_question(id)
                            ON DELETE CASCADE,
            edge_id     TEXT NOT NULL,
            relevant    BOOLEAN NOT NULL,
            note        TEXT,
            judged_by   TEXT,
            judged_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (question_id, edge_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.eval_judgement")
    op.execute("DROP TABLE IF EXISTS public.eval_run")
    op.execute("DROP TABLE IF EXISTS public.eval_question")
