"""track which projects have had a first-run comprehension pass

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-24

A first session in an existing project starts with an empty memory even though
the project itself is months old. Bootstrap sweeps memory *files*, but a
project that never had any is still a blank page, and the codebase's own
knowledge - what it is, how it deploys, what the conventions are, what bit
somebody last time - is nowhere.

This records that a project has had its comprehension pass, so the
session-start briefing asks for one exactly once rather than every session.

Deliberately NOT a place to store the analysis itself. The facts go in the
graph like every other fact, with the same provenance and the same audit
trail; this table only remembers that the pass happened, which sources it
read, and how much it produced.

Why the pass is agent-driven rather than something this server does: deciding
which forty things about a codebase are worth remembering is judgement, and
the server never calls an LLM (design doc, MCP tool contract, architecture
pivot). Importing a structural graph instead was considered and rejected -
graphify already produces one, and for eigen it is 9,321 nodes against this
store's 115 facts, so merging them would bury every recorded decision under
file names.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.project_analysis (
            project TEXT PRIMARY KEY,
            analysed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            n_facts INTEGER NOT NULL DEFAULT 0,
            sources TEXT[] NOT NULL DEFAULT '{}'
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.project_analysis")
