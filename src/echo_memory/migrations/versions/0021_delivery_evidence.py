"""record which facts a read returned, so a claimed recall can be checked

The cross-tool recall save is the criterion this project is graded on, and
until now the server verified only half of it. Both tool identities are derived
from evidence it holds - the writer from the cited edge, the reader from the
presented key - so "two different tools were involved" cannot be asserted by
the caller. But nothing checked that the caller had ever RECEIVED the fact it
cites. record_recall_save took a fact_id and looked it up directly, so an agent
could name a fact it never queried for, and a reviewer of the paper drawn from
this work said so.

read_event already logged every read with its group, tool, session and a COUNT
of facts returned. The count is the useless half: knowing ten facts went out
says nothing about whether this one did. returned_fact_ids stores which.

trial_observation.delivery records how strongly a save was corroborated at the
moment it was filed - 'agent' when a read by that same tool returned the fact,
'group' when some read in the scope did, absent for the saves recorded before
this existed. Stored rather than recomputed, because the read log is a rolling
record and a save's evidence should not change under it.

Neither column is backfilled. Reads before this migration did not record which
facts they returned and no reconstruction is possible; guessing is how a
different metric on this project produced two wrong numbers in one hour.

Revision ID: 0021
Revises: 0020
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.read_event ADD COLUMN IF NOT EXISTS returned_fact_ids TEXT[]"
    )
    # Every lookup is "was this fact id in any read for this group", so the
    # array is the thing being searched and GIN is the index for that.
    op.execute(
        "CREATE INDEX IF NOT EXISTS read_event_returned_facts_idx "
        "ON public.read_event USING GIN (returned_fact_ids)"
    )
    op.execute(
        "ALTER TABLE public.trial_observation ADD COLUMN IF NOT EXISTS delivery TEXT"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS read_event_returned_facts_idx")
    op.execute("ALTER TABLE public.read_event DROP COLUMN IF EXISTS returned_fact_ids")
    op.execute("ALTER TABLE public.trial_observation DROP COLUMN IF EXISTS delivery")
