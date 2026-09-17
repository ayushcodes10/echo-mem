"""index nodes by id, so reading a fact's endpoints is a lookup

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-18

AGE gives its parent tables, _ag_label_vertex and _ag_label_edge, a primary key
on id. The label tables that inherit from them, Node and FACT, get no such
index. FACT has had one since migration 0013, added for a different query and
quietly load bearing ever since. Node has never had one.

That was invisible while every read of a node went through Cypher, because
those were sequential scans anyway and the scan was blamed on AGE. Reading the
node table directly makes the gap visible: a join on Node.id falls back to a
sequential scan of every node in the database, every scope, and in the hosted
service every tenant.

Measured on 2026-09-18 while ingesting LongMemEval: write cost rose from 29ms
at 1,057 nodes to 129ms at 24,054, and throughput over one run fell from 28/s
to 8/s. That had been read as the corpus being large rather than as a defect,
which is the failure mode an index does not announce.

Not partial and not composite. Every use is an equality lookup on a primary
key sized column, which is the one case where a plain btree is exactly right.
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

GRAPH = "echo_memory"


def upgrade() -> None:
    op.execute("LOAD 'age'")
    op.execute('SET search_path = ag_catalog, "$user", public')
    op.execute(f'CREATE INDEX IF NOT EXISTS node_id_idx ON {GRAPH}."Node" (id)')


def downgrade() -> None:
    op.execute("LOAD 'age'")
    op.execute('SET search_path = ag_catalog, "$user", public')
    op.execute(f'DROP INDEX IF EXISTS {GRAPH}.node_id_idx')
