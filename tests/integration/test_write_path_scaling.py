"""One caller's write cost must not depend on how much everybody else wrote.

Twice now a Cypher `MATCH ... WHERE id(x) = $id` in the write path has turned
out to be a sequential scan of every row in the graph, because AGE expands the
match before filtering. Both times the symptom was not an error but a slope:
write throughput fell from 28/s to 8/s over one ingest, which reads as "this
corpus is large" rather than as a defect, and in the hosted service it would
read as one tenant's writes slowing down because a different tenant grew.

Timing assertions would be flaky here, so these read the query plan instead.
A plan is what actually regressed, and it is the thing a future edit would
quietly change.
"""

from __future__ import annotations

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.db import connect
from echo_memory.ingestion.neighbourhood import _endpoints
from echo_memory.ingestion.resolution import _exact_match
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"
FACT = "the deploy branch is master"


def _embedder():
    return VectorEmbedder({
        FACT: REFERENCE,
        "deploy branch": REFERENCE,
        "dugout-be": REFERENCE,
        "deploy branch dugout-be. the deploy branch is master": REFERENCE,
    })


def _seed(conn) -> str:
    result = write_episode(
        conn, GROUP, "s1",
        [{"name": "deploy branch", "type": "thing"},
         {"name": "dugout-be", "type": "thing"}],
        [{"source": "deploy branch", "target": "dugout-be", "relation_type": "is",
          "fact": FACT, "confidence": "extracted"}],
        {"deploy branch": {"resolved_to": "new"}, "dugout-be": {"resolved_to": "new"}},
        _embedder(), agent_id="claude-code",
    )
    return str(result["edges_created"][0])


def _plan(conn, sql: str, params) -> str:
    """The plan with sequential scans priced out of the way.

    A test database holds a handful of rows, where a sequential scan really is
    the cheapest plan and the planner is right to choose it. Asserting on the
    unaided plan would therefore assert on table size rather than on the code.
    What has to stay true regardless of size is that an index path EXISTS for
    these lookups: that is what was missing, and what a future edit could take
    away again without any test noticing.
    """
    # ANALYZE first: without statistics the planner assumes 1,200 rows per
    # table and costs everything off a guess. SET, not SET LOCAL, because these
    # connections are not inside an explicit transaction and a LOCAL setting is
    # discarded the moment the statement ends.
    conn.execute(f'ANALYZE {GRAPH}."Node"')
    conn.execute(f'ANALYZE {GRAPH}."FACT"')
    conn.execute("SET enable_seqscan = off")
    try:
        rows = conn.execute(f"EXPLAIN {sql}", params).fetchall()
    finally:
        conn.execute("RESET enable_seqscan")
    return "\n".join(str(r[0]) for r in rows)


# ------------------------------------------------------------ correctness


def test_an_exact_name_still_resolves(migrated_db):
    with connect(migrated_db) as conn:
        _seed(conn)

        assert _exact_match(conn, GROUP, "DEPLOY BRANCH")[1] == "deploy branch"
        assert _exact_match(conn, GROUP, "nothing here") is None


def test_a_name_in_another_scope_is_not_a_match(migrated_db):
    """The group filter is the whole point of reading off the table directly;
    losing it would be a cross tenant resolution."""
    with connect(migrated_db) as conn:
        _seed(conn)

        assert _exact_match(conn, "user:someone-else:shared", "deploy branch") is None


def test_an_alias_still_resolves(migrated_db):
    """The alias branch runs on every miss, so it has to keep working as well
    as stay inside the scope."""
    with connect(migrated_db) as conn:
        _seed(conn)
        conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH (n:Node) WHERE n.name = 'dugout-be'
                SET n.aliases = ['dugout backend'] RETURN id(n)
            $$) AS (i agtype)"""
        ).fetchall()

        assert _exact_match(conn, GROUP, "Dugout Backend")[1] == "dugout-be"
        assert _exact_match(conn, "user:someone-else:shared", "dugout backend") is None


def test_endpoints_returns_both_entities_in_the_caller_s_order(migrated_db):
    with connect(migrated_db) as conn:
        edge_id = _seed(conn)

        found = _endpoints(conn, [edge_id])

    assert len(found) == 1
    assert found[0]["fact"] == FACT
    assert [name for _id, name in found[0]["ends"]] == ["deploy branch", "dugout-be"]


def test_endpoints_ignores_an_edge_id_that_does_not_exist(migrated_db):
    with connect(migrated_db) as conn:
        _seed(conn)

        assert _endpoints(conn, ["999999999999"]) == []


# ------------------------------------------------------------ the plan


def test_resolving_a_name_does_not_scan_every_node(migrated_db):
    """Migration 0016 built node_name_per_group_idx on (group_id, lower(name))
    for exactly this lookup, and until 2026-09-18 the lookup went through
    Cypher and could not reach it."""
    with connect(migrated_db) as conn:
        _seed(conn)
        plan = _plan(
            conn,
            f"""SELECT id::text FROM {GRAPH}."Node"
                WHERE (properties ->> '"group_id"'::agtype) = %s
                  AND lower((properties ->> '"name"'::agtype)) = lower(%s)
                LIMIT 1""",
            (GROUP, "deploy branch"),
        )

    assert "node_name_per_group_idx" in plan or "node_group_idx" in plan, plan


def test_reading_a_fact_s_endpoints_can_go_by_id(migrated_db):
    """Both ends are reached by primary key. Through Cypher this same read
    walked every FACT edge in the database once per id, which is how a write
    ended up costing what the whole store had ever written."""
    with connect(migrated_db) as conn:
        edge_id = _seed(conn)
        plan = _plan(
            conn,
            f"""SELECT e.id::text FROM {GRAPH}."FACT" e
                JOIN {GRAPH}."Node" s ON s.id = e.start_id
                JOIN {GRAPH}."Node" t ON t.id = e.end_id
                WHERE e.id = ANY(SELECT unnest(%s::text[])::graphid)""",
            ([edge_id],),
        )

    assert "Index Scan" in plan, plan
    assert "Seq Scan" not in plan, plan


@pytest.mark.parametrize("name", ["deploy branch", "DEPLOY BRANCH", "Deploy Branch"])
def test_case_does_not_decide_identity(migrated_db, name):
    with connect(migrated_db) as conn:
        _seed(conn)

        assert _exact_match(conn, GROUP, name) is not None
