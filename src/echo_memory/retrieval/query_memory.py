"""query_memory: 2-signal retrieval (pgvector + full-text) fused with RRF
(see the design doc's Recommended Approach, v1a section). Both candidate
lists are pre-filtered to active facts (t_invalid IS NULL) before ranking,
not after: see MATHS.local.md §7 for why post-hoc filtering is wrong even
for a plain ranked list, not just for PPR's probability-mass case in v1b."""

import json
import math
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
# Fallback only. The floor that actually runs is measured per store by
# `adaptive_cosine_floor` below; this is what a store too small to measure
# against falls back to.
COSINE_FLOOR = 0.15
TS_RANK_FLOOR = 0.0

# How many random query/fact pairs to sample when measuring the noise floor,
# and how many facts a store needs before measuring is better than guessing.
FLOOR_SAMPLE = 200
FLOOR_MIN_FACTS = 30
# The percentile of that noise distribution to sit above. 95 lets one in twenty
# unrelated facts through, which RRF then discounts by rank.
FLOOR_PERCENTILE = 95

# Maximal Marginal Relevance. 1.0 is pure relevance and reproduces the old
# behaviour; 0.0 is pure novelty and ignores the question. 0.7 keeps relevance
# dominant while breaking up runs of near-identical facts, which is the failure
# being fixed rather than a general preference for variety.
MMR_LAMBDA = 0.7

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


def _mmr_select(conn, group_id: str, ranked_ids: list[str], top_k: int) -> list[str]:
    """Pick top_k that are relevant AND not near-duplicates of each other.

    The ranked list is scored purely on similarity to the query, so several
    phrasings of one fact all score well and all get selected. The user pays
    for every one of them in injected tokens and learns nothing from the second
    onwards - the same failure the capture queue has, arriving through
    retrieval instead.

    Standard MMR: repeatedly take the candidate maximising
        lambda * rel(d) - (1 - lambda) * max_{s in selected} sim(d, s)
    Relevance is the fused rank, already computed. Similarity between
    candidates comes from the embeddings that are already stored, so this costs
    one extra query and no model calls.

    Falls back to the plain ranked order if the embeddings cannot be read - a
    less diverse answer is much better than no answer.
    """
    if len(ranked_ids) <= 1 or top_k <= 1:
        return ranked_ids[:top_k]

    try:
        rows = conn.execute(
            """SELECT edge_id::text, embedding FROM public.fact_embedding
               WHERE group_id = %s AND edge_id::text = ANY(%s)""",
            (group_id, list(ranked_ids)),
        ).fetchall()
    except Exception:  # noqa: BLE001 - see docstring
        _logger.warning("mmr_skipped", extra={"reason": "embeddings unreadable"})
        return ranked_ids[:top_k]

    # pgvector hands back a Vector, not a list, and it is not iterable.
    vectors = {
        edge_id: (vec.to_list() if hasattr(vec, "to_list") else list(vec))
        for edge_id, vec in rows
    }
    if len(vectors) < len(ranked_ids):
        # Some candidate has no embedding; ranking it against the others would
        # be arbitrary. Not worth a partial reorder.
        return ranked_ids[:top_k]

    # Relevance from position: the list is already in fused-score order, and
    # only the ordering matters to MMR, not the scale.
    relevance = {eid: 1.0 - (i / len(ranked_ids)) for i, eid in enumerate(ranked_ids)}

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na and nb else 0.0

    selected: list[str] = [ranked_ids[0]]
    remaining = [e for e in ranked_ids[1:]]
    while remaining and len(selected) < top_k:
        best, best_score = None, None
        for candidate in remaining:
            redundancy = max(
                cosine(vectors[candidate], vectors[chosen]) for chosen in selected
            )
            score = MMR_LAMBDA * relevance[candidate] - (1 - MMR_LAMBDA) * redundancy
            if best_score is None or score > best_score:
                best, best_score = candidate, score
        selected.append(best)
        remaining.remove(best)
    return selected


def adaptive_cosine_floor(conn, group_id: str) -> float:
    """The similarity an unrelated fact actually scores in THIS store.

    A fixed 0.15 was measured to sit inside the noise rather than above it:
    unrelated-fact similarity in this store runs 0.084-0.163 with sd
    0.078-0.135, so a floor at 0.15 admits roughly half of everything. That is
    why an abstract question returns cron bugs - the floor was never filtering.

    Measuring beats picking a better constant. The right value depends on the
    embedder, the length of the facts and the subject matter, all of which
    differ per store and drift as one grows. Sampling random pairs of facts
    approximates the query-to-unrelated-fact distribution well enough to place
    a percentile, and costs one query.

    Falls back to COSINE_FLOOR on a store too small to measure - under
    FLOOR_MIN_FACTS the sample is mostly noise about noise.
    """
    row = conn.execute(
        """
        WITH sampled AS (
            SELECT embedding FROM public.fact_embedding
            WHERE group_id = %s ORDER BY random() LIMIT %s
        ), pairs AS (
            SELECT -(a.embedding <#> b.embedding) AS sim
            FROM sampled a, sampled b
            -- Every unordered pair once, and never a fact against itself,
            -- which scores 1.0 and would drag the percentile up.
            WHERE a.embedding <> b.embedding
        )
        SELECT count(*), percentile_cont(%s) WITHIN GROUP (ORDER BY sim)
        FROM pairs
        """,
        (group_id, FLOOR_SAMPLE, FLOOR_PERCENTILE / 100.0),
    ).fetchone()

    if not row or not row[0] or row[1] is None:
        return COSINE_FLOOR
    n_pairs, percentile = row
    # n_pairs is quadratic in the sample, so this is the fact count squared.
    if n_pairs < FLOOR_MIN_FACTS * FLOOR_MIN_FACTS:
        return COSINE_FLOOR
    # Never below the static floor: a store whose facts are all near-identical
    # would otherwise measure a floor of nearly zero and admit everything.
    return max(COSINE_FLOOR, float(percentile))


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
    floor = adaptive_cosine_floor(conn, group_id)
    return [edge_id for edge_id, score in rows if score >= floor]


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
    """Batch-fetch fact/confidence/causal_hint/provenance/agent_id/project for a
    set of edge ids via one Cypher UNWIND query, not N+1 lookups.

    `agent_id` is returned because `record_recall_save` asks the caller for
    `written_by`, and until 2026-08-28 the only documented source for that value
    was "visible on every query_memory result as agent_id" - a field this
    function did not return. An agent following the instruction found nothing
    and had to guess or skip, which is one of three reasons the v1a cross-tool
    criterion had never once been satisfied. It has been on the edge and indexed
    (`fact_group_agent_idx`) since migration 0003; only the read path was
    missing."""
    if not edge_ids:
        return {}
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            UNWIND $ids AS eid
            MATCH ()-[e:FACT]->() WHERE id(e) = eid
            RETURN id(e), e.fact, e.confidence, e.causal_hint, e.provenance,
                   e.agent_id, e.project
        $$, %s) AS (edge_id agtype, fact agtype, confidence agtype,
                     causal_hint agtype, provenance agtype, agent_id agtype,
                     project agtype)""",
        (json.dumps({"ids": [int(i) for i in edge_ids]}),),
    ).fetchall()
    return {
        str(edge_id): {
            "fact_id": str(edge_id),
            "fact": _agtype_str(fact),
            "confidence": _agtype_str(confidence),
            "causal_hint": _agtype_str(causal_hint),
            "provenance": _provenance(provenance, agent_id, project),
        }
        for edge_id, fact, confidence, causal_hint, provenance, agent_id, project in rows
    }


def _provenance(raw, agent_id, project) -> dict | None:
    """Attribution belongs inside `provenance` rather than beside it: session and
    episode already live there, and a caller asking "where did this come from?"
    should find every part of the answer in one place."""
    out = json.loads(str(raw)) if raw is not None else {}
    if not isinstance(out, dict):
        out = {"episode": out}
    out["agent_id"] = _agtype_str(agent_id)
    out["project"] = _agtype_str(project)
    return out


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
        # ANY-term, not websearch_to_tsquery's implicit AND.
        #
        # The AND form requires every non-stopword term of the query to appear
        # in the fact. "deploy branch policy" against a fact about the deploy
        # branch matches nothing, because "policy" is absent. Measured on six
        # realistic questions against twenty real facts, exactly one returned
        # anything - so RRF was fusing a populated vector list with an empty
        # lexical one and reproducing the vector ordering exactly. That is also
        # why k=60 and LIST_DEPTH=50 read as low-leverage: they have never had
        # two lists to fuse.
        #
        # This function already existed for the hook path, thirty lines above,
        # where the same behaviour had been found and worked around. The tool
        # path kept the version that does not work, and the pair looked
        # deliberate.
        lexical_ids = _lexical_any_candidates(conn, group_id, query, LIST_DEPTH)
        fused = reciprocal_rank_fusion([vector_ids, lexical_ids])
        by_score = sorted(fused, key=fused.get, reverse=True)
        # Diversify before truncating, not after: the point is to choose which
        # top_k, and slicing first throws away the candidates MMR would swap in.
        ranked_ids = _mmr_select(conn, group_id, by_score[:LIST_DEPTH], top_k)

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
