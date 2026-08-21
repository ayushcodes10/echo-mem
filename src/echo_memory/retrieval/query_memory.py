"""query_memory: 2-signal retrieval (pgvector + full-text) fused with RRF
(see the design doc's Recommended Approach, v1a section). Both candidate
lists are pre-filtered to active facts (t_invalid IS NULL) before ranking,
not after: see MATHS.local.md §7 for why post-hoc filtering is wrong even
for a plain ranked list, not just for PPR's probability-mass case in v1b."""

import json
import time

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.logging import get_logger, log_query_memory
from echo_memory.retrieval.fusion import LIST_DEPTH, reciprocal_rank_fusion

DEFAULT_TOP_K = 10
MAX_TOP_K = 100

# Score floors: a ranker with nothing useful to say shouldn't cast a rank-1
# vote worth as much as a ranker's genuine top match (see MATHS.local.md
# §3). Lowered from an initial 0.3 after it silently hid a real result in
# manual testing: "what database" vs "using SQLite for now" scores 0.281
# with the real embedder, a genuine match, but below 0.3. Query-to-fact
# similarity (short colloquial question vs. a full sentence) runs lower
# than entity-name-to-entity-name similarity (§5's thresholds), so this
# can't reuse those values. Still a placeholder pending real calibration,
# deliberately conservative: hiding a real memory is worse than including
# a mediocre one, which RRF's fusion already discounts by rank anyway.
COSINE_FLOOR = 0.15
TS_RANK_FLOOR = 0.0

_logger = get_logger("query_memory")


class ValidationError(Exception):
    pass


def _validate(query: str | None, top_k: int, digest: bool) -> None:
    if not digest and (not query or not query.strip()):
        raise ValidationError("query must not be empty")
    if not isinstance(top_k, int) or top_k < 1:
        raise ValidationError(f"top_k must be a positive integer, got {top_k!r}")
    if top_k > MAX_TOP_K:
        raise ValidationError(f"top_k must be at most {MAX_TOP_K}, got {top_k}")


def _vector_candidates(conn, group_id: str, embedding: list[float], limit: int) -> list[str]:
    rows = conn.execute(
        f"""
        SELECT fe.edge_id::text, -(fe.embedding <#> %s::vector) AS score
        FROM public.fact_embedding fe
        JOIN {GRAPH}."FACT" f ON f.id = fe.edge_id
        WHERE fe.group_id = %s
          AND (f.properties ->> '"t_invalid"'::agtype) IS NULL
        ORDER BY fe.embedding <#> %s::vector
        LIMIT %s
        """,
        (embedding, group_id, embedding, limit),
    ).fetchall()
    return [edge_id for edge_id, score in rows if score >= COSINE_FLOOR]


def _lexical_candidates(conn, group_id: str, query: str, limit: int) -> list[str]:
    rows = conn.execute(
        f"""
        SELECT f.id::text,
               ts_rank(to_tsvector('english', f.properties ->> '"fact"'::agtype),
                        websearch_to_tsquery('english', %s)) AS score
        FROM {GRAPH}."FACT" f
        WHERE (f.properties ->> '"group_id"'::agtype) = %s
          AND (f.properties ->> '"t_invalid"'::agtype) IS NULL
          AND to_tsvector('english', f.properties ->> '"fact"'::agtype)
              @@ websearch_to_tsquery('english', %s)
        ORDER BY score DESC
        LIMIT %s
        """,
        (query, group_id, query, limit),
    ).fetchall()
    return [edge_id for edge_id, score in rows if score > TS_RANK_FLOOR]


def _digest_candidates(conn, group_id: str, limit: int) -> list[str]:
    """No query text to rank against: a digest is "catch me up," not "answer
    this," so it's the most recently valid active facts, chronological, not
    relevance-ranked. See the CEO plan's scope decision #2 (session-start
    context digest, opt-in, no auto-injection)."""
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT {{group_id: $gid}}]->()
            WHERE e.t_invalid IS NULL
            RETURN id(e)
            ORDER BY e.t_valid DESC
            LIMIT $limit
        $$, %s) AS (edge_id agtype)""",
        (json.dumps({"gid": group_id, "limit": limit}),),
    ).fetchall()
    return [str(edge_id) for (edge_id,) in rows]


def _agtype_str(v):
    return str(v).strip('"') if v is not None else None


def _fetch_facts(conn, edge_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch fact/confidence/causal_hint/provenance for a set of edge
    ids via one Cypher UNWIND query, not N+1 lookups."""
    if not edge_ids:
        return {}
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            UNWIND $ids AS eid
            MATCH ()-[e:FACT]->() WHERE id(e) = eid
            RETURN id(e), e.fact, e.confidence, e.causal_hint, e.provenance
        $$, %s) AS (edge_id agtype, fact agtype, confidence agtype,
                     causal_hint agtype, provenance agtype)""",
        (json.dumps({"ids": [int(i) for i in edge_ids]}),),
    ).fetchall()
    return {
        str(edge_id): {
            "fact_id": str(edge_id),
            "fact": _agtype_str(fact),
            "confidence": _agtype_str(confidence),
            "causal_hint": _agtype_str(causal_hint),
            "provenance": json.loads(str(provenance)) if provenance is not None else None,
        }
        for edge_id, fact, confidence, causal_hint, provenance in rows
    }


def query_memory(
    conn, group_id: str, query: str | None, top_k: int, embedder, digest: bool = False
) -> dict:
    """top_k has no default here: DEFAULT_TOP_K=10 is applied at the MCP tool
    schema layer (PR5), which is the natural place to declare it, rather
    than baking a default into every internal caller of this function.

    digest=True ignores query (may be None) and returns the most recently
    valid active facts instead of ranking against a query string: an opt-in
    "catch me up" convenience for session start, explicitly invoked, never
    auto-triggered (see the CEO plan's scope decision #2)."""
    start = time.perf_counter()
    try:
        _validate(query, top_k, digest)
    except ValidationError as e:
        log_query_memory(
            _logger, group_id, 0, 0, 0, (time.perf_counter() - start) * 1000, error=str(e)
        )
        return {"error": str(e)}

    if digest:
        ranked_ids = _digest_candidates(conn, group_id, top_k)
        vector_ids, lexical_ids = [], []
    else:
        embedding = embedder.embed(query)
        vector_ids = _vector_candidates(conn, group_id, embedding, LIST_DEPTH)
        lexical_ids = _lexical_candidates(conn, group_id, query, LIST_DEPTH)
        fused = reciprocal_rank_fusion([vector_ids, lexical_ids])
        ranked_ids = sorted(fused, key=fused.get, reverse=True)[:top_k]

    facts_by_id = _fetch_facts(conn, ranked_ids)
    facts = [facts_by_id[edge_id] for edge_id in ranked_ids if edge_id in facts_by_id]

    log_query_memory(
        _logger,
        group_id,
        len(vector_ids),
        len(lexical_ids),
        len(facts),
        (time.perf_counter() - start) * 1000,
    )
    return {"facts": facts}
