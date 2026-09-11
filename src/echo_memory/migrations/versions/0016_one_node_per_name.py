"""one node per name per scope, enforced by the database

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-11

Entity resolution prevents a duplicate by reading before it writes: look for an
exact name match, and create a node only if there is none. That is a
check-then-act, and nothing has ever made it atomic.

One writer, and the read is a good enough proxy for the truth. Two writers -
Claude Code and Cursor in the same second, or any two agents on one hosted
account - and both can read "no such node" before either commits. Both create,
and the store has one entity split in two with no error anywhere.

This is a real gap rather than a theoretical one: two nodes named 'Eigon
warm-base ALB sharing' were written minutes apart by one session, through a
different hole in the same check, and nothing objected. The write path now
refuses to skip the read; this makes the outcome impossible rather than
unlikely.

Case-insensitive because _exact_match is: a node found by `toLower(n.name) =
toLower($name)` must not be creatable by a differently-cased write.
agtype_access_operator is IMMUTABLE, which is what lets it be indexed at all.
"""

from alembic import op

from echo_memory.infra.db import GRAPH_NAME as GRAPH

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def prop(key: str) -> str:
    return f"(properties ->> '\"{key}\"'::agtype)"


def upgrade() -> None:
    op.execute("LOAD 'age'")
    op.execute('SET search_path = ag_catalog, "$user", public')
    # A store that already holds a collision cannot take the index, and a
    # migration is the wrong place to decide which of two entities survives -
    # that judgement belongs to `echo-memory merge`, which moves the facts and
    # keeps the folded-in name as an alias. So this reports rather than guesses.
    op.execute(f"""
        DO $$
        DECLARE collisions int;
        BEGIN
            SELECT count(*) INTO collisions FROM (
                SELECT 1 FROM {GRAPH}."Node"
                GROUP BY {prop("group_id")}, lower({prop("name")}::text)
                HAVING count(*) > 1
            ) AS t;
            IF collisions > 0 THEN
                RAISE EXCEPTION USING MESSAGE =
                    format('%s name collision(s) already exist; fold each pair '
                           'together with `echo-memory merge --into <id> --from <id>` '
                           'and run this again. `echo-memory trial check` lists them '
                           'under "same name, same scope".', collisions);
            END IF;
        END $$;
    """)
    op.execute(
        f'CREATE UNIQUE INDEX IF NOT EXISTS node_name_per_group_idx ON {GRAPH}."Node" '
        f'({prop("group_id")}, lower({prop("name")}::text))'
    )


def downgrade() -> None:
    op.execute("LOAD 'age'")
    op.execute('SET search_path = ag_catalog, "$user", public')
    op.execute(f'DROP INDEX IF EXISTS {GRAPH}.node_name_per_group_idx')
