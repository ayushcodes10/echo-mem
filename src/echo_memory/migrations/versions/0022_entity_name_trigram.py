"""Add an indexed lexical signal for entity resolution.

Embedding similarity treats identifiers that differ by one meaningful token as
near-duplicates.  Keep a trigram index on the canonical AGE node name so the
resolver can retrieve those candidates without scanning the graph.

Revision ID: 0022
Revises: 0021
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

GRAPH = "echo_memory"


def _property(key: str) -> str:
    return f"(properties ->> '\"{key}\"'::agtype)"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        f"CREATE INDEX node_name_trgm_idx ON {GRAPH}.\"Node\" "
        f"USING GIN ({_property('name')} gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS echo_memory.node_name_trgm_idx")
