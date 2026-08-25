"""query_memory: 2-signal retrieval (pgvector + full-text) fused with RRF
(see the design doc's Recommended Approach, v1a section). Both candidate
lists are pre-filtered to active facts (t_invalid IS NULL) before ranking,
not after: see MATHS.local.md §7 for why post-hoc filtering is wrong even
for a plain ranked list, not just for PPR's probability-mass case in v1b."""

import json
import re
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


def _any_term_tsquery(terms: list[str]) -> tuple[str, list[str]]:
    """An OR-of-terms tsquery, built by OR-ing per-term plainto_tsquery calls.

    websearch_to_tsquery ANDs every term, which is right when the query is a
    deliberate search and wrong when it is a whole sentence somebody typed at
    an agent: "is chat-module-api dev or prod" requires every one of chat,
    modul, api, dev and prod to appear in the same fact, and a fact that says
    exactly the right thing still misses because the hostname tokenises as one
    token and never yields a bare 'api'. Measured, not assumed - that prompt
    matched nothing against a fact written to answer it.

    Each term still goes through plainto_tsquery rather than being pasted into
    a to_tsquery string, so user text is never interpreted as tsquery syntax.
    That is the rule the design doc's security review set and it survives here:
    the OR is composed from sanitised pieces, not from raw input."""
    placeholders = " || ".join(["plainto_tsquery('english', %s)"] * len(terms))
    return f"({placeholders})", terms


# Words too common to carry signal, on top of Postgres's own stopwords. A
# prompt is full of them and each one drags in unrelated facts.
_NOISE_TERMS = frozenset(
    ["the", "a", "an", "is", "are", "was", "were", "be", "do", "does", "did", "can", "could", "should", "would", "will", "what", "why", "how", "when", "where", "who", "which", "this", "that", "these", "those", "and", "or", "not", "for", "from", "with", "about", "into", "you", "your", "we", "our", "it", "its", "me", "my", "please", "help", "need", "want"]
)
MAX_TERMS = 12


def prompt_terms(prompt: str) -> list[str]:
    """The words worth searching for in a typed prompt."""
    seen, terms = set(), []
    for raw in re.split(r"[^\w.\-/]+", prompt.lower()):
        word = raw.strip("-./")
        if len(word) < 3 or word in _NOISE_TERMS or word in seen:
            continue
        seen.add(word)
        terms.append(word)
    return terms[:MAX_TERMS]


def _lexical_any_candidates(conn, group_id: str, query: str, limit: int) -> list[str]:
    """Lexical retrieval that matches ANY salient term, ranked. Used by the
    prompt-time recall path; the main query path keeps AND semantics, which is
    correct for a deliberate query and is what v1a's retrieval was tested on."""
    terms = prompt_terms(query)
    if not terms:
        return []
    tsquery, params = _any_term_tsquery(terms)
    rows = conn.execute(
        f"""
        SELECT f.id::text,
               ts_rank(to_tsvector('english', f.properties ->> '"fact"'::agtype),
                        {tsquery}) AS score
        FROM {GRAPH}."FACT" f
        WHERE (f.properties ->> '"group_id"'::agtype) = %s
          AND (f.properties ->> '"t_invalid"'::agtype) IS NULL
          AND to_tsvector('english', f.properties ->> '"fact"'::agtype) @@ {tsquery}
        ORDER BY score DESC
        LIMIT %s
        """,
        (*params, group_id, *params, limit),
    ).fetchall()
    return [edge_id for edge_id, score in rows if score > TS_RANK_FLOOR]


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
    context digest, opt-in, no auto-injection).

    t_valid is second-granularity, so two facts written within the same
    second tie on it; id(e) DESC breaks the tie deterministically by
    creation order (AGE assigns ids monotonically per label)."""
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT {{group_id: $gid}}]->()
            WHERE e.t_invalid IS NULL
            RETURN id(e)
            ORDER BY e.t_valid DESC, id(e) DESC
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
    conn, group_id: str, query: str | None, top_k: int, embedder,
    digest: bool = False, lexical_only: bool = False,
) -> dict:
    """top_k has no default here: DEFAULT_TOP_K=10 is applied at the MCP tool
    schema layer (PR5), which is the natural place to declare it, rather
    than baking a default into every internal caller of this function.

    digest=True ignores query (may be None) and returns the most recently
    valid active facts instead of ranking against a query string: an opt-in
    "catch me up" convenience for session start, explicitly invoked, never
    auto-triggered (see the CEO plan's scope decision #2).

    lexical_only=True drops the vector signal and ranks on Postgres full-text
    search alone. It exists for one caller: the UserPromptSubmit hook, which
    runs in a fresh process on every prompt and therefore cannot afford to load
    the embedding model - measured at 6.2 seconds of cold start (see
    cli/benchmark.py). FTS needs no model, so that path costs milliseconds.

    The tradeoff is real and worth stating: lexical matching finds facts that
    share words with the prompt and misses ones that only share meaning, which
    is exactly what the vector signal is for. Recall here is deliberately worse
    than a full query_memory call. It is the difference between some relevant
    memory arriving automatically and none arriving at all, not between good
    retrieval and bad."""
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
    elif lexical_only:
        vector_ids = []
        lexical_ids = _lexical_any_candidates(conn, group_id, query, LIST_DEPTH)
        ranked_ids = lexical_ids[:top_k]
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
