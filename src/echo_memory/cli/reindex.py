"""echo-memory reindex: re-embed every fact with the current embedding text.

Not a migration, deliberately. Alembic runs SQL against a connection; this
needs the embedding model, which is a 90MB download and several seconds of
work per thousand facts. Putting that in `init-db` would make a schema upgrade
silently depend on network access and turn a fast, safe operation into a slow
one that can fail halfway.

So it is a command you run when the embedding text changes, and the reason it
exists is that the embedding text just did: entity names are now prepended to
the fact before embedding, and a fact written before that carries a vector of
the fact alone. Mixed vectors do not error - they quietly rank worse than
either convention would on its own, which is the kind of failure nobody
notices.

Idempotent. Running it twice produces the same vectors, so it is safe to re-run
after an interrupted pass.
"""

from __future__ import annotations

import json

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.ingestion.write_episode import embedding_text


def facts_needing_embedding(conn, group_ids: list[str]) -> list[tuple[str, str, str, str]]:
    """(edge_id, source_name, target_name, fact) for every active fact.

    Retired facts are skipped: nothing retrieves them, so re-embedding them
    spends model time on rows no query will ever rank.
    """
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (a:Node)-[e:FACT]->(b:Node)
            WHERE e.group_id IN $gids AND e.t_invalid IS NULL
            RETURN id(e), a.name, b.name, e.fact
        $$, %s) AS (edge_id agtype, a agtype, b agtype, fact agtype)""",
        (json.dumps({"gids": list(group_ids)}),),
    ).fetchall()
    return [
        (str(edge_id), str(a).strip('"'), str(b).strip('"'), str(fact).strip('"'))
        for edge_id, a, b, fact in rows
    ]


def reindex(conn, group_ids: list[str], embedder, progress=None) -> dict:
    """Re-embed in place. One UPDATE per fact rather than a rebuild, so an
    interrupted run leaves a store that is partly reindexed rather than one
    with no vectors at all."""
    facts = facts_needing_embedding(conn, group_ids)
    updated = 0
    for i, (edge_id, source, target, fact) in enumerate(facts, start=1):
        conn.execute(
            "UPDATE public.fact_embedding SET embedding = %s WHERE edge_id = %s::graphid",
            (embedder.embed(embedding_text(source, target, fact)), edge_id),
        )
        updated += 1
        if progress and i % 25 == 0:
            progress(i, len(facts))
    return {"facts": len(facts), "updated": updated}


def render(result: dict) -> str:
    if not result["facts"]:
        return "nothing to reindex: this scope has no active facts.\n"
    return (
        f"Re-embedded {result['updated']} of {result['facts']} active fact(s) "
        f"with entity names included.\n"
        f"Run `echo-memory eval` to see what it did to retrieval.\n"
    )
