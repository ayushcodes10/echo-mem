"""Folding a confirmed duplicate back into one node.

The review queue could say "these two are the same entity" and nothing could
act on it, so a confirmed duplicate stayed two nodes and every later mention had
to pick between them. This is the missing half of `unmerge`.

The part that needs testing is not the graph edit. Apache AGE cannot move a
relationship's endpoints, so each fact is recreated and the original deleted,
which changes its edge id - and `fact_embedding` is keyed by edge id. Miss that
and the fact still exists in the graph and silently stops being retrievable,
which is worse than losing it outright.
"""

from __future__ import annotations

import json

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.cli.merge import MergeError, merge
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.db import connect
from echo_memory.ingestion.resolution import _exact_match
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"
OTHER = "user:someone-else:shared"
KEEP, DROP, THIRD = "ALB sharing", "warm-base ALB sharing", "Eigon planner"
KEEP_FACT = "every environment pays for its own ALB"
DROP_FACT = "the cause was ordering, not logic"
LINK_FACT = "the planner reads the hostname from env.URL"


def _embedder():
    return VectorEmbedder({
        KEEP: REFERENCE, DROP: REFERENCE, THIRD: REFERENCE,
        KEEP_FACT: REFERENCE, DROP_FACT: REFERENCE, LINK_FACT: REFERENCE,
    })


def _write(conn, group, source, target, fact, session="s1"):
    names = list(dict.fromkeys([source, target]))
    write_episode(
        conn, group, session,
        [{"name": n, "type": "thing"} for n in names],
        [{"source": source, "target": target, "relation_type": "is",
          "fact": fact, "confidence": "extracted"}],
        {n: {"resolved_to": "new"} for n in names},
        _embedder(), agent_id="claude-code", project="echo-mem",
    )


def _id(conn, group, name):
    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node {{group_id: $gid}}) WHERE n.name = $name RETURN id(n)
        $$, %s) AS (i agtype)""",
        (json.dumps({"gid": group, "name": name}),),
    ).fetchone()
    return str(row[0]) if row else None


def _split_store(conn):
    """Two nodes that are one entity, one of them also linked to a third."""
    _write(conn, GROUP, KEEP, KEEP, KEEP_FACT)
    _write(conn, GROUP, DROP, DROP, DROP_FACT)
    _write(conn, GROUP, THIRD, DROP, LINK_FACT)
    return _id(conn, GROUP, KEEP), _id(conn, GROUP, DROP)


def _facts_on(conn, node_id):
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (a)-[e:FACT]->(b) WHERE id(a) = $nid OR id(b) = $nid RETURN e.fact
        $$, %s) AS (f agtype)""",
        (json.dumps({"nid": int(node_id)}),),
    ).fetchall()
    return {str(r[0]).strip('"') for r in rows}


def test_every_fact_follows_the_entity(migrated_db):
    with connect(migrated_db) as conn:
        keep, drop = _split_store(conn)

        result = merge(conn, GROUP, "s-merge", keep, drop)

        assert result["facts_moved"] == 2
        assert _facts_on(conn, keep) == {KEEP_FACT, DROP_FACT, LINK_FACT}
        assert _id(conn, GROUP, DROP) is None


def test_the_vectors_follow_the_facts(migrated_db):
    """The failure this is really guarding. A recreated edge has a new id, and
    fact_embedding is keyed by edge id - leave it behind and the fact is in the
    graph, invisible to retrieval, with nothing to show anything is wrong."""
    with connect(migrated_db) as conn:
        keep, drop = _split_store(conn)
        merge(conn, GROUP, "s-merge", keep, drop)

        orphaned = conn.execute(
            f"""SELECT count(*) FROM public.fact_embedding fe
                 WHERE NOT EXISTS (
                     SELECT 1 FROM cypher('{GRAPH}', $$
                         MATCH ()-[e:FACT]->() RETURN id(e) $$) AS t(i agtype)
                     WHERE t.i::text = fe.edge_id::text)"""
        ).fetchone()[0]
        assert orphaned == 0, "a vector was left pointing at a deleted edge"

        edges = conn.execute(
            f"""SELECT count(*) FROM cypher('{GRAPH}', $$
                MATCH ()-[e:FACT {{group_id: '{GROUP}'}}]->() RETURN id(e)
            $$) AS (i agtype)"""
        ).fetchone()[0]
        vectors = conn.execute(
            "SELECT count(*) FROM public.fact_embedding WHERE group_id = %s", (GROUP,)
        ).fetchone()[0]
        assert edges == vectors == 3


def test_the_dropped_name_still_resolves_to_the_survivor(migrated_db):
    """Otherwise this is a deletion with extra steps: the next mention of the
    folded-in name would create the duplicate all over again."""
    with connect(migrated_db) as conn:
        keep, drop = _split_store(conn)
        merge(conn, GROUP, "s-merge", keep, drop)

        match = _exact_match(conn, GROUP, DROP)

    assert match is not None and match[0] == keep


def test_the_merge_is_in_the_audit_log(migrated_db):
    with connect(migrated_db) as conn:
        keep, drop = _split_store(conn)
        merge(conn, GROUP, "s-merge", keep, drop)

        rows = conn.execute(
            """SELECT mutation_type::text, summary FROM public.audit_entry
                WHERE session_id = 's-merge'"""
        ).fetchall()

    assert len(rows) == 1
    assert DROP in rows[0][1] and KEEP in rows[0][1]


def test_a_node_cannot_be_merged_into_itself(migrated_db):
    with connect(migrated_db) as conn:
        keep, _ = _split_store(conn)
        with pytest.raises(MergeError):
            merge(conn, GROUP, "s-merge", keep, keep)


def test_another_scopes_node_is_refused(migrated_db):
    """Both ends. Merging across scopes would move one tenant's facts onto
    another's entity, which is the cross-tenant write with a different name."""
    with connect(migrated_db) as conn:
        keep, drop = _split_store(conn)
        _write(conn, OTHER, KEEP, KEEP, KEEP_FACT, session="s2")
        theirs = _id(conn, OTHER, KEEP)

        with pytest.raises(MergeError):
            merge(conn, GROUP, "s-merge", keep, theirs)
        with pytest.raises(MergeError):
            merge(conn, OTHER, "s-merge", theirs, drop)

        assert _facts_on(conn, theirs) == {KEEP_FACT}
        assert _id(conn, GROUP, DROP) is not None, "a refused merge deleted a node"


def test_facts_keep_their_provenance(migrated_db):
    """A recreated edge is the same fact. Losing who wrote it, when, or in what
    project would make a repair look like a rewrite."""
    with connect(migrated_db) as conn:
        keep, drop = _split_store(conn)
        merge(conn, GROUP, "s-merge", keep, drop)

        rows = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH ()-[e:FACT {{group_id: $gid}}]->()
                WHERE e.fact = $fact
                RETURN e.agent_id, e.project, e.provenance.session_id, e.confidence
            $$, %s) AS (a agtype, p agtype, s agtype, c agtype)""",
            (json.dumps({"gid": GROUP, "fact": DROP_FACT}),),
        ).fetchone()

    assert [str(x).strip('"') for x in rows] == ["claude-code", "echo-mem", "s1", "extracted"]
