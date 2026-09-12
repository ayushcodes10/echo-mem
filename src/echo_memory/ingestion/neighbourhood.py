"""What this episode should probably have connected to.

The store this was built in has 246 entities in its shared scope and a median
degree of 1: 147 of them (60%) appear in exactly one fact. The shape is a
handful of project hubs carrying 14 to 35 edges and a long tail of leaves that
each turn up once and are never mentioned again. The solo scope is the same,
63% at degree <= 1.

That is a write-time outcome, not a retrieval one. Every episode arrives with
its own freshly invented names, gets two new nodes, joins them to each other,
and stops. Nothing in the write path ever tells the agent that the graph
already has a word for what it is describing, so nothing pulls successive
episodes onto shared vocabulary.

It matters because multi-hop retrieval - the next version's whole argument - is
a traversal, and a traversal across a median-degree-1 graph leaves a leaf,
reaches its project hub and stops. The premise of the next phase is not
supported by the data this phase produces, and no amount of work on the read
path fixes that.

So: after an episode is written, find the facts already in the scope that are
nearest to what was just written, and name the entities they connect.

**Similarity between fact texts, not between names.** Entity resolution scores
name against name and was calibrated on this store at AUC 0.666, 95% CI
[0.421, 0.881] - an interval containing chance. Fact-text retrieval on the same
store measures R@1 0.949 and MRR 0.970 on the prose query shape. One of those
two signals is worth building on. This rides the one that works.

**Advisory, and only advisory.** The episode is already committed when this
runs. It cannot block a write, change a resolution, or add an edge. Inventing a
connection nobody asserted would be worse than the sparsity it is trying to
fix: a memory graph is only worth reading if every edge in it was claimed by
somebody.
"""

from __future__ import annotations

import json

from echo_memory.infra.db import GRAPH_NAME as GRAPH

# Enough for an agent to notice a word it should have used, few enough that the
# response does not become something to skim. Suggestions past the fifth have
# never been the reason anyone reused a name.
DEFAULT_LIMIT = 5

# How many neighbouring facts to look at before picking entities out of them.
# Larger than the entity limit because several facts usually name the same
# entity, and because the nearest fact's two endpoints are often the ones
# already excluded.
FACT_DEPTH = 20

# Facts per episode that get their own query. An episode of forty facts is a
# bulk import, not somebody recording what just happened, and running forty
# vector searches to advise it would put the cost on exactly the caller who
# least needs the advice.
MAX_FACTS_CONSULTED = 3


def _clean(value) -> str:
    """AGE returns strings as quoted agtype."""
    return str(value).strip('"')


def _endpoints(conn, edge_ids: list[str]) -> list[dict]:
    """The two entities each of these facts connects, in one query.

    Ordered by the caller's list rather than by the database, so the nearest
    fact's entities come first and rank the result.
    """
    if not edge_ids:
        return []
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            UNWIND $ids AS eid
            MATCH (s)-[e:FACT]->(t) WHERE id(e) = eid
            RETURN id(e), e.fact, id(s), s.name, id(t), t.name
        $$, %s) AS (edge_id agtype, fact agtype, source_id agtype, source agtype,
                     target_id agtype, target agtype)""",
        (json.dumps({"ids": [int(i) for i in edge_ids]}),),
    ).fetchall()

    by_edge = {
        str(edge_id): {
            "fact": _clean(fact),
            "ends": [(str(source_id), _clean(source)), (str(target_id), _clean(target))],
        }
        for edge_id, fact, source_id, source, target_id, target in rows
    }
    return [dict(by_edge[e], edge_id=e) for e in edge_ids if e in by_edge]


def _adjacent(conn, node_ids: list[str]) -> set[str]:
    """Node ids already one hop from any of these.

    Suggesting an entity the episode is already connected to is noise: the edge
    exists, so reusing the name changes nothing about the graph's shape.
    """
    if not node_ids:
        return set()
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            UNWIND $ids AS nid
            MATCH (n)-[:FACT]-(m) WHERE id(n) = nid
            RETURN id(m)
        $$, %s) AS (node_id agtype)""",
        (json.dumps({"ids": [int(i) for i in node_ids]}),),
    ).fetchall()
    return {str(r[0]) for r in rows}


def related_entities(
    conn,
    group_id: str,
    embeddings: list[list[float]],
    *,
    written_node_ids: list[str],
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    """Entities already in this scope that the episode arguably belongs near.

    Returns, for each, its node id, its name, and the existing fact that made
    it relevant - the fact matters more than the name, because "you already
    have an entity called X" is an assertion the agent has no reason to trust,
    while "this fact is about the same thing and it uses X" is evidence.

    Excludes the episode's own entities and anything already adjacent to them,
    so every suggestion is a connection that does not yet exist.

    Takes one embedding per fact rather than one per episode. An episode's
    facts share entities but not necessarily a subject - "X caused Y" and "X is
    owned by Z" are one call and two topics - so collapsing them into a single
    query would answer for whichever fact happened to be first.
    """
    from echo_memory.retrieval.query_memory import _vector_candidates

    edge_ids: list[str] = []
    for embedding in embeddings[:MAX_FACTS_CONSULTED]:
        for edge_id in _vector_candidates(conn, group_id, embedding, FACT_DEPTH):
            if edge_id not in edge_ids:
                edge_ids.append(edge_id)
    if not edge_ids:
        return []

    written = set(written_node_ids)
    skip = written | _adjacent(conn, written_node_ids)

    out: list[dict] = []
    seen: set[str] = set()
    for neighbour in _endpoints(conn, edge_ids):
        for node_id, name in neighbour["ends"]:
            if node_id in skip or node_id in seen:
                continue
            seen.add(node_id)
            out.append({
                "node_id": node_id,
                "name": name,
                "because": neighbour["fact"],
            })
            if len(out) >= limit:
                return out
    return out
