"""Taking back an alias one entity absorbed from another.

A confirmed `resolved_to` points the episode's facts at the named node AND
appends the mention to that node's aliases. The second half is what makes a
misdirected resolution a merge rather than a misfiled fact: the node now
answers to both names, which is criterion 6's "two distinct entities
incorrectly merged into one node" word for word.

Both of this store's confirmed bad merges were still live when this was
written, eight days after being found. The 2026-09-02 cleanup deleted the
misdirected edges, which was the visible half, and left the aliases - so
'node_embedding table' still answered to 'Eigon billing profile'. _exact_match
checks aliases, so the damage was not historical: the next mention of that name
could land on an embedding table's lesson.
"""

from __future__ import annotations

import json

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.cli.unmerge import UnmergeError, foreign_aliases, unmerge
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.db import connect
from echo_memory.ingestion.resolution import _exact_match
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"
OTHER_GROUP = "user:someone-else:shared"

TABLE = "node_embedding table"
BILLING = "Eigon billing profile"


def _embedder():
    return VectorEmbedder({
        TABLE: REFERENCE, BILLING: REFERENCE,
        "a lesson about the embedding table": REFERENCE,
        "a fact about Indian tax compliance": REFERENCE,
    })


def _node(conn, group, name, fact):
    write_episode(
        conn, group, "s1",
        [{"name": name, "type": "thing"}],
        [{"source": name, "target": name, "relation_type": "is",
          "fact": fact, "confidence": "extracted"}],
        {name: {"resolved_to": "new"}},
        _embedder(), agent_id="claude-code",
    )
    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node {{group_id: $gid}}) WHERE n.name = $name RETURN id(n)
        $$, %s) AS (i agtype)""",
        (json.dumps({"gid": group, "name": name}),),
    ).fetchone()
    return str(row[0])


def _absorb(conn, node_id, alias):
    """What a confirmed resolved_to does to the node it points at."""
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE id(n) = $nid
            SET n.aliases = $aliases RETURN id(n)
        $$, %s) AS (i agtype)""",
        (json.dumps({"nid": int(node_id), "aliases": [alias]}),),
    ).fetchall()


def _merged_store(conn):
    table = _node(conn, GROUP, TABLE, "a lesson about the embedding table")
    billing = _node(conn, GROUP, BILLING, "a fact about Indian tax compliance")
    _absorb(conn, table, BILLING)
    return table, billing


def test_a_node_answering_to_another_nodes_name_is_found(migrated_db):
    with connect(migrated_db) as conn:
        table, billing = _merged_store(conn)
        found = foreign_aliases(conn, GROUP)

    assert len(found) == 1
    assert found[0]["node_id"] == table
    assert found[0]["alias"] == BILLING
    assert found[0]["alias_owner_id"] == billing


def test_a_nodes_own_name_among_its_aliases_is_not_a_merge(migrated_db):
    """Every node records itself that way. Reporting it would bury the two real
    ones under twenty that are fine."""
    with connect(migrated_db) as conn:
        table = _node(conn, GROUP, TABLE, "a lesson about the embedding table")
        _absorb(conn, table, TABLE)
        assert foreign_aliases(conn, GROUP) == []


def test_unmerging_stops_the_alias_resolving_onto_the_wrong_node(migrated_db):
    """The assertion that matters. Deleting the misdirected edges left this
    behaviour untouched for eight days: _exact_match checks aliases, so the
    next mention of the absorbed name could still land on the wrong entity."""
    with connect(migrated_db) as conn:
        table, billing = _merged_store(conn)

        # Retire the rightful owner, so the alias is the only match left and
        # the landmine is visible rather than masked by the node's own name.
        conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH (n:Node) WHERE id(n) = $nid SET n.name = 'renamed' RETURN id(n)
            $$, %s) AS (i agtype)""",
            (json.dumps({"nid": int(billing)}),),
        ).fetchall()

        before = _exact_match(conn, GROUP, BILLING)
        assert before is not None and before[0] == table, "the merge was not reproduced"

        unmerge(conn, GROUP, "s-repair", table, BILLING)

        assert _exact_match(conn, GROUP, BILLING) is None


def test_the_repair_is_in_the_audit_log(migrated_db):
    """A repair that leaves no trace is how the first half of this cleanup came
    to look complete."""
    with connect(migrated_db) as conn:
        table, _ = _merged_store(conn)
        unmerge(conn, GROUP, "s-repair", table, BILLING)

        rows = conn.execute(
            """SELECT mutation_type::text, summary, resolution_detail
                 FROM public.audit_entry WHERE session_id = 's-repair'""",
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "entity_resolved"
    assert BILLING in rows[0][1] and TABLE in rows[0][1]


def test_another_scopes_node_cannot_be_edited(migrated_db):
    with connect(migrated_db) as conn:
        theirs = _node(conn, OTHER_GROUP, TABLE, "a lesson about the embedding table")
        _absorb(conn, theirs, BILLING)

        with pytest.raises(UnmergeError) as e:
            unmerge(conn, GROUP, "s-repair", theirs, BILLING)

    assert "not a node in this scope" in str(e.value)


def test_an_alias_that_is_not_there_is_refused(migrated_db):
    with connect(migrated_db) as conn:
        table, _ = _merged_store(conn)
        with pytest.raises(UnmergeError):
            unmerge(conn, GROUP, "s-repair", table, "something else entirely")


def test_a_node_cannot_be_stripped_of_its_own_name(migrated_db):
    """It would leave the node unable to match itself, which is a different and
    worse kind of broken than answering to one name too many."""
    with connect(migrated_db) as conn:
        table = _node(conn, GROUP, TABLE, "a lesson about the embedding table")
        _absorb(conn, table, TABLE)
        with pytest.raises(UnmergeError) as e:
            unmerge(conn, GROUP, "s-repair", table, TABLE)

    assert "own name" in str(e.value)
