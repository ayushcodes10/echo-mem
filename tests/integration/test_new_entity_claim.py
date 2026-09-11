"""Claiming an entity is new does not make it new.

`entity_resolutions[name]["resolved_to"] = "new"` was taken entirely on trust
and skipped resolution altogether - including the exact name match that would
otherwise have found the node. So a caller asserting novelty for a name its own
scope already holds got a second node with the same name, which is criterion
6's duplicate bar: one entity split in two.

Not hypothetical. Two nodes named 'Eigon warm-base ALB sharing' sit in this
author's store, written minutes apart by one session that said "new" both
times. A duplicate created by entity resolution, by the one path that skips
entity resolution.

Case-insensitive name equality is this system's definition of identity - drop
the resolutions dict and the same mention resolves to the same node - so the
match wins over the assertion. Anything else creates an entity that the next
mention silently merges back.
"""

from __future__ import annotations

import json

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"
OTHER = "user:someone-else:shared"
NAME = "Eigon warm-base ALB sharing"
FIRST = "warm-base ALB sharing has never actually happened"
SECOND = "the cause was ordering, not logic"


def _embedder():
    return VectorEmbedder({NAME: REFERENCE, FIRST: REFERENCE, SECOND: REFERENCE,
                           NAME.lower(): REFERENCE})


def _claim_new(conn, group, fact, name=NAME, session="s1"):
    return write_episode(
        conn, group, session,
        [{"name": name, "type": "thing"}],
        [{"source": name, "target": name, "relation_type": "is",
          "fact": fact, "confidence": "extracted"}],
        {name: {"resolved_to": "new"}},
        _embedder(), agent_id="claude-code",
    )


def _nodes_named(conn, group, name):
    return conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node {{group_id: $gid}})
            WHERE toLower(n.name) = toLower($name) RETURN id(n)
        $$, %s) AS (i agtype)""",
        (json.dumps({"gid": group, "name": name}),),
    ).fetchall()


def test_two_claims_of_the_same_name_make_one_node(migrated_db):
    """The live duplicate, reproduced. Before this, two."""
    with connect(migrated_db) as conn:
        assert _claim_new(conn, GROUP, FIRST).get("edges_created")
        assert _claim_new(conn, GROUP, SECOND).get("edges_created")

        assert len(_nodes_named(conn, GROUP, NAME)) == 1


def test_the_second_episodes_facts_reach_the_existing_node(migrated_db):
    """Overriding the claim has to keep the write working. Refusing it would
    turn a duplicate into a lost episode, which is worse."""
    with connect(migrated_db) as conn:
        _claim_new(conn, GROUP, FIRST)
        _claim_new(conn, GROUP, SECOND)

        node = _nodes_named(conn, GROUP, NAME)[0][0]
        facts = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH (a)-[e:FACT]->(b) WHERE id(a) = {int(str(node))}
                RETURN e.fact
            $$) AS (f agtype)"""
        ).fetchall()

    assert {str(f[0]).strip('"') for f in facts} == {FIRST, SECOND}


def test_the_override_is_visible_in_the_audit_log(migrated_db):
    """A resolution that silently contradicts what the caller asked for has to
    say so, or the next person debugging a 'missing' node has nothing to read."""
    with connect(migrated_db) as conn:
        _claim_new(conn, GROUP, FIRST)
        _claim_new(conn, GROUP, SECOND, session="s2")

        details = conn.execute(
            """SELECT resolution_detail FROM public.audit_entry
                WHERE session_id = 's2' AND mutation_type = 'entity_resolved'""",
        ).fetchall()

    assert any("overridden" in str(d[0]) for d in details), details


def test_a_differently_cased_claim_is_the_same_entity(migrated_db):
    """_exact_match is case-insensitive, so the override has to be too -
    otherwise the duplicate comes back through a capital letter."""
    with connect(migrated_db) as conn:
        _claim_new(conn, GROUP, FIRST)
        _claim_new(conn, GROUP, SECOND, name=NAME.lower())

        assert len(_nodes_named(conn, GROUP, NAME)) == 1


def test_another_scope_may_still_hold_that_name(migrated_db):
    """Solo and shared are separate namespaces. The same name in two scopes is
    correct scoping, not a duplicate - which is exactly what the trial's one
    recorded 'duplicate' turned out to be."""
    with connect(migrated_db) as conn:
        _claim_new(conn, GROUP, FIRST)
        _claim_new(conn, OTHER, SECOND)

        assert len(_nodes_named(conn, GROUP, NAME)) == 1
        assert len(_nodes_named(conn, OTHER, NAME)) == 1


def test_a_genuinely_new_name_is_still_new(migrated_db):
    with connect(migrated_db) as conn:
        _claim_new(conn, GROUP, FIRST)
        assert len(_nodes_named(conn, GROUP, NAME)) == 1
