"""index the facts that are actually queried

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-09

Every hot read carries `t_invalid IS NULL`. Both candidate lists are filtered
to active facts before ranking, not after (see the retrieval module's docstring
and MATHS.local.md §7 for why post-hoc filtering is wrong), so that predicate is
on the vector path, the lexical path and the digest path alike.

Nothing indexed it. Retired facts are never deleted - the whole point of the
bitemporal model is that they stay readable as history - so the table only ever
grows and the share of it that any query wants only ever shrinks. At 253 facts
with zero retired that costs nothing, which is exactly why it is worth adding
before it does.

A partial index rather than a plain one on t_invalid: the queries never ask for
retired facts, so indexing them wastes the space twice over.
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

GRAPH = "echo_memory"


def prop(key: str) -> str:
    return f"(properties ->> '\"{key}\"'::agtype)"


def upgrade() -> None:
    op.execute("LOAD 'age'")
    op.execute('SET search_path = ag_catalog, "$user", public')

    # The lexical and digest paths both scan FACT filtered by group and active
    # state. group_id leads because it is the more selective of the two in a
    # multi-tenant store, and it is an equality match.
    op.execute(
        f'CREATE INDEX IF NOT EXISTS fact_active_group_idx ON {GRAPH}."FACT" '
        f'(({prop("group_id")})) WHERE {prop("t_invalid")} IS NULL'
    )

    # The vector path joins fact_embedding to FACT and then filters on the same
    # predicate, so it needs the id side covered too.
    op.execute(
        f'CREATE INDEX IF NOT EXISTS fact_active_id_idx ON {GRAPH}."FACT" '
        f'(id) WHERE {prop("t_invalid")} IS NULL'
    )


def downgrade() -> None:
    op.execute("LOAD 'age'")
    op.execute('SET search_path = ag_catalog, "$user", public')
    op.execute(f"DROP INDEX IF EXISTS {GRAPH}.fact_active_id_idx")
    op.execute(f"DROP INDEX IF EXISTS {GRAPH}.fact_active_group_idx")
