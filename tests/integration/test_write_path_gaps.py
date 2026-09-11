"""Two things a write must never leave behind: a node nothing can reach, and a
fact nothing can filter.

Both are the same shape as the agent_id bug and both were found by querying the
author's own store rather than by a test. Apache AGE drops a property whose
value is null at CREATE, so a missing value is a missing key, and nothing reads
as wrong until something asks a question the key was for.
"""

from __future__ import annotations

import json

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.db import connect
from echo_memory.infra.project import UNKNOWN
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"
USED = "entity_pair query shape"
UNUSED = "lexical channel in query_memory"
FACT = "the default query shape leaks the answer"


def _embedder():
    return VectorEmbedder({USED: REFERENCE, UNUSED: REFERENCE, FACT: REFERENCE})


def _write(conn, **kw):
    return write_episode(
        conn, GROUP, "s1",
        [{"name": USED, "type": "shape"}, {"name": UNUSED, "type": "component"}],
        [{"source": USED, "target": USED, "relation_type": "is",
          "fact": FACT, "confidence": "extracted"}],
        {USED: {"resolved_to": "new"}, UNUSED: {"resolved_to": "new"}},
        _embedder(), agent_id="claude-code", **kw,
    )


def _node_names(conn):
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node {{group_id: $gid}}) RETURN n.name
        $$, %s) AS (n agtype)""",
        (json.dumps({"gid": GROUP}),),
    ).fetchall()
    return {str(r[0]).strip('"') for r in rows}


def test_an_entity_no_fact_mentions_gets_no_node(migrated_db):
    """A caller that names four entities and writes facts about three used to
    get a fourth node with no edges: unreachable by query_memory, which searches
    facts, and counted forever in every pair the duplicate scanner considers.
    No follow-up call rescues it either - nothing references it, so nothing
    will ever give it an edge."""
    with connect(migrated_db) as conn:
        result = _write(conn)

        assert result.get("edges_created")
        assert _node_names(conn) == {USED}


def test_a_fact_always_carries_a_project(migrated_db):
    """Seven facts in the author's store carry no project key at all. A fact
    with no project gives its nodes no project, and duplicate_candidates drops
    any pair with no project in common - so the entity goes invisible to the
    queue built to catch exactly that."""
    with connect(migrated_db) as conn:
        _write(conn, project="")

        absent = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH ()-[e:FACT {{group_id: $gid}}]->()
                WHERE e.project IS NULL RETURN count(e)
            $$, %s) AS (n agtype)""",
            (json.dumps({"gid": GROUP}),),
        ).fetchone()
        assert int(str(absent[0])) == 0, "a fact was written with no project key"

        stored = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH ()-[e:FACT {{group_id: $gid}}]->() RETURN e.project
            $$, %s) AS (p agtype)""",
            (json.dumps({"gid": GROUP}),),
        ).fetchone()
        assert str(stored[0]).strip('"') == UNKNOWN


def test_a_real_project_is_left_alone(migrated_db):
    """The coercion must not overwrite what the caller actually said."""
    with connect(migrated_db) as conn:
        _write(conn, project="echo-mem")

        stored = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH ()-[e:FACT {{group_id: $gid}}]->() RETURN e.project
            $$, %s) AS (p agtype)""",
            (json.dumps({"gid": GROUP}),),
        ).fetchone()
        assert str(stored[0]).strip('"') == "echo-mem"
