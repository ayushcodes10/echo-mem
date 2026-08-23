"""trial instrumentation: recorded observations against v1a criterion 6

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-23

Criterion 6 in docs/designs/echo-memory-design.md's Success Criteria is the
v1a -> v1b gate: 3+ real instances where a recalled fact saved re-explaining
something to a different tool, at most 1 duplicate node, zero incorrectly
merged entities, over a trial capped at 3 weeks. Every one of those bars
needs a human judgement, which is exactly why none of them were being
recorded anywhere: the gate was decidable only from memory. These two tables
give each judgement somewhere to live, so `echo-memory status` can report the
gate from stored data like it already does for criteria 1, 2 and 4.

Deliberately separate from `audit_entry` rather than new mutation_type enum
values on it: the audit log is the append-only record of what memory *did*
(see the design doc's auditability premise), and a human's note about whether
a merge was correct isn't a memory mutation. Mixing them would make
`echo-memory why` show trial bookkeeping in a fact's history.

`node_ids` is TEXT[], not graphid[] like audit_entry.affected_node_id: these
are references typed by a human reviewing `echo-memory trial check` output,
kept as the text form that output prints, not foreign keys the database
resolves. A judged pair is stored sorted so the same two nodes can't be
judged twice under swapped order.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

DEFAULT_CAP_DAYS = 21


def upgrade() -> None:
    op.execute("""
        CREATE TYPE public.trial_observation_kind AS ENUM (
            'recall_save', 'duplicate_node', 'not_duplicate', 'bad_merge', 'merge_ok'
        )
    """)
    op.execute("""
        CREATE TABLE public.trial_observation (
            id BIGSERIAL PRIMARY KEY,
            "timestamp" TIMESTAMPTZ NOT NULL DEFAULT now(),
            kind public.trial_observation_kind NOT NULL,
            group_id TEXT NOT NULL,
            note TEXT NOT NULL,
            -- recall_save only: which tool originally wrote the fact and which
            -- one recalled it. Criterion 6 counts an instance only when these
            -- differ; that "different tool" clause is the whole point of the bar.
            written_by TEXT,
            recalled_by TEXT,
            -- duplicate_node / not_duplicate: the pair judged, sorted
            node_ids TEXT[],
            -- bad_merge / merge_ok: the entity_resolved audit entry reviewed
            audit_entry_id BIGINT REFERENCES public.audit_entry (id)
        )
    """)
    op.execute(
        'CREATE INDEX trial_observation_group_idx '
        'ON public.trial_observation (group_id, "timestamp")'
    )
    # One verdict per reviewed resolution, so `trial check` can exclude what's
    # already been judged by a plain NOT IN and never re-ask.
    op.execute(
        "CREATE UNIQUE INDEX trial_observation_audit_entry_idx "
        "ON public.trial_observation (audit_entry_id) WHERE audit_entry_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX trial_observation_pair_idx "
        "ON public.trial_observation (group_id, node_ids) WHERE node_ids IS NOT NULL"
    )

    # Singleton: the trial has one start date and one cap. The CHECK on a
    # BOOLEAN primary key is the standard way to let the table hold exactly
    # one row without application code enforcing it.
    op.execute(f"""
        CREATE TABLE public.trial_run (
            id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
            started_on DATE NOT NULL,
            cap_days INTEGER NOT NULL DEFAULT {DEFAULT_CAP_DAYS}
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.trial_run")
    op.execute("DROP TABLE IF EXISTS public.trial_observation")
    op.execute("DROP TYPE IF EXISTS public.trial_observation_kind")
