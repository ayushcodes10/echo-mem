"""echo-memory merge: fold one node into another, once they are confirmed to be
one entity.

`unmerge` exists because a bad merge left an alias behind. This is the other
direction and the one with no tool at all until now: the review queue can say
"these two are the same entity" and nothing could act on it, so a confirmed
duplicate stayed two nodes and the graph kept a split entity that every later
mention had to pick between.

Apache AGE cannot move a relationship's endpoints, so each fact is recreated
against the surviving node and the original deleted. That is the whole reason
this is delicate: an edge's id changes, and `fact_embedding` is keyed by edge
id, so the vector has to move with it or the fact silently drops out of
retrieval while still existing in the graph. Everything happens in one
transaction for that reason.

Deliberately not automatic. It runs on two ids a human has confirmed, because
the calibration says name similarity cannot make this call - confirmed-same and
confirmed-distinct pairs overlap across the whole usable range - and merging is
the direction that loses information.
"""

from __future__ import annotations

import json
import re

from echo_memory.infra.db import GRAPH_NAME as GRAPH

# Property names are interpolated into Cypher, so they are checked rather than
# trusted. Every key this project writes is a plain identifier.
_SAFE_KEY = re.compile(r"[a-z_][a-z0-9_]*")


class MergeError(Exception):
    pass


def _identity(conn, group_id: str, node_id: str) -> tuple[str, list[str]] | None:
    try:
        wanted = int(node_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE id(n) = $nid AND n.group_id = $gid
            RETURN n.name, n.aliases
        $$, %s) AS (name agtype, aliases agtype)""",
        (json.dumps({"nid": wanted, "gid": group_id}),),
    ).fetchone()
    if row is None:
        return None
    aliases = json.loads(str(row[1])) if row[1] is not None else []
    return str(row[0]).strip('"'), [str(a) for a in aliases or []]


def _facts_touching(conn, node_id: str) -> list[dict]:
    """Every fact with this node at either end, with its properties and the
    other endpoint, so each can be recreated exactly."""
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (a)-[e:FACT]->(b)
            WHERE id(a) = $nid OR id(b) = $nid
            RETURN id(e), id(a), id(b), properties(e)
        $$, %s) AS (eid agtype, aid agtype, bid agtype, props agtype)""",
        (json.dumps({"nid": int(node_id)}),),
    ).fetchall()
    out = []
    for eid, aid, bid, props in rows:
        text = str(props)
        # agtype appends a type suffix on composite values.
        for suffix in ("::edge", "::vertex", "::path"):
            text = text.removesuffix(suffix)
        out.append({
            "edge_id": str(eid), "source": str(aid), "target": str(bid),
            "properties": json.loads(text),
        })
    return out


def merge(conn, group_id: str, session_id: str, keep_id: str, drop_id: str) -> dict:
    """Move everything from drop_id onto keep_id and delete drop_id."""
    if str(keep_id) == str(drop_id):
        raise MergeError("a node cannot be merged into itself")

    keep = _identity(conn, group_id, keep_id)
    drop = _identity(conn, group_id, drop_id)
    if keep is None:
        raise MergeError(f"node {keep_id} is not a node in this scope")
    if drop is None:
        raise MergeError(f"node {drop_id} is not a node in this scope")

    keep_name, keep_aliases = keep
    drop_name, drop_aliases = drop

    moved = 0
    for fact in _facts_touching(conn, drop_id):
        source = keep_id if fact["source"] == str(drop_id) else fact["source"]
        target = keep_id if fact["target"] == str(drop_id) else fact["target"]
        # A fact whose two endpoints were the two nodes being merged becomes a
        # self-edge on the survivor, which is the correct reading: it was always
        # a statement about one entity.
        # AGE has no `SET e = $map`, so the property map is spelled out from
        # whatever keys the original carried. Built from the keys rather than a
        # fixed list, so a property added later moves with the fact instead of
        # being quietly dropped by a repair tool nobody thought to update.
        keys = [k for k in fact["properties"] if _SAFE_KEY.fullmatch(k)]
        if len(keys) != len(fact["properties"]):
            raise MergeError(
                f"fact {fact['edge_id']} has a property name this cannot safely "
                f"rebuild: {sorted(set(fact['properties']) - set(keys))}"
            )
        prop_map = ", ".join(f"{k}: $props.{k}" for k in keys)
        row = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH (a), (b)
                WHERE id(a) = $sid AND id(b) = $tid
                  AND a.group_id = $gid AND b.group_id = $gid
                CREATE (a)-[e:FACT {{{prop_map}}}]->(b)
                RETURN id(e)
            $$, %s) AS (eid agtype)""",
            (json.dumps({
                "sid": int(source), "tid": int(target),
                "gid": group_id, "props": fact["properties"],
            }),),
        ).fetchone()
        if row is None:
            raise MergeError(f"could not recreate fact {fact['edge_id']}")
        new_edge = str(row[0])

        # The vector moves with the fact. Without this the fact still exists in
        # the graph and silently stops being retrievable, which is the worst of
        # both outcomes.
        conn.execute(
            """UPDATE public.fact_embedding SET edge_id = %s::text::graphid
                WHERE edge_id::text = %s""",
            (new_edge, fact["edge_id"]),
        )
        conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH ()-[e:FACT]->() WHERE id(e) = $eid DELETE e RETURN 1
            $$, %s) AS (x agtype)""",
            (json.dumps({"eid": int(fact["edge_id"])}),),
        ).fetchall()
        moved += 1

    # The dropped name becomes an alias, because a mention of it must resolve
    # to the survivor from now on - that is what makes this a merge rather than
    # a deletion with extra steps.
    aliases = list(dict.fromkeys([*keep_aliases, keep_name, drop_name, *drop_aliases]))
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE id(n) = $nid AND n.group_id = $gid
            SET n.aliases = $aliases RETURN id(n)
        $$, %s) AS (i agtype)""",
        (json.dumps({"nid": int(keep_id), "gid": group_id, "aliases": aliases}),),
    ).fetchall()

    conn.execute(
        "DELETE FROM public.node_embedding WHERE node_id::text = %s", (str(drop_id),)
    )
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE id(n) = $nid AND n.group_id = $gid
            DETACH DELETE n RETURN 1
        $$, %s) AS (x agtype)""",
        (json.dumps({"nid": int(drop_id), "gid": group_id}),),
    ).fetchall()

    conn.execute(
        """INSERT INTO public.audit_entry
               (group_id, session_id, mutation_type, affected_node_id, summary,
                resolution_detail)
           VALUES (%s, %s, 'entity_resolved', %s::text::graphid, %s, %s)""",
        (
            group_id, session_id, str(keep_id),
            f"merged {drop_name!r} into {keep_name!r}",
            f"{moved} fact(s) moved; {drop_name!r} kept as an alias",
        ),
    )
    return {
        "kept": keep_name, "dropped": drop_name,
        "facts_moved": moved, "aliases": aliases,
    }


def run(args, config, conn) -> int:
    group_id = config.group_id(args.scope)
    try:
        result = merge(conn, group_id, args.session_id or "cli", args.into, getattr(args, "from"))
    except MergeError as e:
        print(f"error: {e}")
        return 1
    print(
        f"Merged {result['dropped']!r} into {result['kept']!r}: "
        f"{result['facts_moved']} fact(s) moved, "
        f"{len(result['aliases'])} alias(es) on the survivor."
    )
    return 0
