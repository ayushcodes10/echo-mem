# Echo Memory — Design

Status: Draft, pre-implementation. This document is the source of truth for the
architecture and build sequence — see the PR Plan section for the current
dependency-ordered implementation order.

## Problem Statement

Two problems, one system:

1. **Personal, felt pain (the validated wedge):** switching between AI coding tools
   (Claude Code ↔ Cursor, etc.) loses context. You re-explain decisions and state every
   time you switch. This is the specific, tested pain v1a's exit criteria measure — real
   demand evidence, not a hypothesis.
2. **Market gap, confirmed by research:** no open-source agent-memory system combines
   (a) graph edges that carry real payload, (b) retrieval beyond plain cosine similarity,
   (c) explicit causal-relation typing, and (d) clean multi-tenancy, in one package —
   AND, per your explicit decision, without depending on a third-party AI-memory framework
   (Graphiti, cognee, FalkorDB) that could constrain how the resulting tool is licensed
   or shipped.

**Vision, distinct from the validated wedge above (added after this session's scope
broadening):** the same architecture generalizes past coding agents specifically — any
MCP-compatible agent (chatbots, DevOps/ops agents, deployed agentic systems, internal
business tooling) can read/write the same memory graph, and the tenancy model (single
agent → shared-per-user → org-wide) already scales from one developer's local setup to an
organization running agentic systems in production. **This is honestly a vision, not yet
something v1a tests** — v1a's exit criteria stay scoped to the validated coding-tool
wedge; the broader positioning is what the architecture is built toward, evaluated once
the narrow wedge proves the mechanism actually works.

Echo Memory is an open-source tool addressing all of this: your own daily pain first,
built as infrastructure you fully own and others — any agent, any scale — can adopt
without inheriting a vendor's license terms.

## What Makes This Cool

- Edges carry real payload (facts, confidence, temporal validity, provenance) — hand-
  designed, not inherited from a framework's schema. Causal typing (below) is a v1b
  addition once the core loop is proven.
- **v1b:** retrieval combines vector + lexical + graph-centrality (Personalized PageRank,
  via `networkx`), not just cosine similarity — cheaper and better at multi-hop "how did
  we get here" queries. **v1a ships vector + lexical only** — proving basic recall works
  before adding multi-hop sophistication.
- **v1b:** causality modeled explicitly (`caused_by`, `led_to`, `enabled_by`, `blocked_by`,
  `contradicts`), set by the agent's own judgment at write-time — not statistically
  inferred. The honest, tractable version of "causal search."
- One database engine (Postgres, with pgvector always, Apache AGE added in v1b) handles
  storage, vector search, and (in v1b) native graph traversal — not three bolted-together
  systems, and the same engine that runs a solo user's local memory scales unmodified to
  org-wide concurrent multi-writer use. No migration debt baked in from day one. (This
  does mean a running Postgres process, not a single file — see Distribution Plan. And
  separately: the embedding call for vector search and the LLM call for extraction are
  external API calls regardless of storage choice — the database is self-hosted, the
  model calls aren't.)
- One tenancy mechanism scales from your own cross-tool memory to a shared team/org graph.
- **Day-to-day usage:** an agent calls the MCP server's write tool at natural checkpoints
  in a session (decisions made, preferences stated) and its query tool at session start or
  when it needs prior context — not automatic background injection in v1. **This
  mechanism itself is unverified** — see Premise 7 and the Next Steps spike.

## Constraints

- Solo build, no team yet.
- Must be genuinely open source and adoptable — not a personal script, and not built on
  a dependency whose own license terms could constrain that.
- Prioritize correctness and honesty about what's solved vs. research-stage over
  impressive-sounding but unproven techniques (e.g. statistical causal discovery,
  covariance-weighted distance).
- **v1 is single-user, local-only.** No cross-user auth model, no org-wide ACL enforcement
  — deferred to v1.1 (see Recommended Approach).
- **Sensitive data is an accepted v1 risk, not silently ignored.** Real coding-session data
  can contain secrets/tokens in `fact` strings even at single-user local scope. v1 accepts
  this the same way existing local session logs already on disk are accepted. A
  best-effort secret-scrubbing pass at ingestion is worth adding cheaply if it doesn't
  block the timeline; full redaction policy is v1.1.
- **v1a and v1b are a real, gated staging split**, not just a scheduling note — v1b work
  does not start until v1a's exit criteria (see the CEO plan) are met. `causal_hint`, AGE,
  and PPR are all v1b, together — none of them are needed to test whether basic recall
  reduces re-explaining, which is the actual felt pain this project exists to solve.

## Premises

1. **Own the memory/graph engine outright; use permissively-licensed generic infra as
   foundations, not AI-memory frameworks.** Depending on Graphiti/cognee/FalkorDB carries
   license and vendor-control risk in the layer that matters (the memory logic itself).
   Generic, battle-tested, permissively-licensed building blocks (**PostgreSQL**,
   **pgvector**, **Apache AGE**, **numpy/scipy**, **networkx** — see Premise 6) are not
   competitors and carry none of that risk.
2. **Pick the final, scalable storage architecture now — no staged "simple v1, migrate
   later" plan.** SQLite structurally cannot support the org-wide, concurrent multi-writer
   tier this design commits to (Premise 4). Postgres+pgvector+AGE is the one engine used
   from single-agent through org-wide, no rewrite implied. Confirmed as the strongest fit
   on accessibility (universally hosted), cost (free-tier everywhere), correctness
   (decades of ACID hardening), and speed (real MVCC concurrency).
3. **Don't attempt statistical causal discovery, ever.** Genuinely unsolved for agent
   memory per landscape research; model causality as an explicit, agent-classified edge
   type instead (v1b).
4. **Multi-tenancy uses one mechanism at three scopes**, not three different systems:
   `group_id` namespacing for single-agent, multi-agent-same-user, and org-wide (with ACL
   on an `access` field). **v1 ships the first two scopes only; org-wide + ACL is v1.1.**
   The storage engine already supports the third scope's concurrency needs — v1.1 adds
   auth/ACL logic on top, not a database migration.
5. **This still solves the founder's own real pain** (cross-tool context loss), now scoped
   as something shareable, and now something you fully control the license of, on an
   architecture that doesn't need to be rebuilt as it grows.
6. **v1a is decoupled from Apache AGE entirely — corrected after an outside-voice review
   caught this design coupling v1a's schema to AGE despite v1a doing zero graph
   traversal.** v1a ships on plain Postgres tables (identical shape to what AGE would
   store — see Concrete Schema). AGE, `causal_hint`, and PPR are a single v1b bundle,
   gated together on v1a's exit criteria. This also closes a real gap the same review
   caught: converting AGE-vertex data to plain tables *after* v1a shipped with real data
   in it would itself be a migration — the exact thing Premise 2 exists to avoid. Shipping
   v1a AGE-free removes that risk entirely. Separately: PPR is computed via **`networkx`'s
   `personalized_pagerank`** directly (BSD-licensed, generic graph-math library — same
   category as numpy/scipy, not an AI-memory framework) rather than hand-rolled sparse
   power iteration — the plan was already going to validate hand-rolled PPR against
   `networkx` as a correctness reference, so using it directly removes an entire class of
   "our reimplementation has a subtle bug the validation didn't catch" risk.
7. **The core mechanism this project depends on — agents reliably calling `write_episode`/
   `query_memory` at natural checkpoints — is unverified and gets spiked before v1a
   proceeds.** An outside-voice review pointed out that if Claude Code/Cursor don't
   reliably invoke these tools without being told to, the whole value proposition (reduced
   re-explaining) doesn't materialize regardless of how good the retrieval is underneath.

## Landscape (researched 2026-08-20 — kept as context, not as a dependency list)

The research below is still valuable: it tells us what already exists (so we don't
duplicate solved ideas) and what's genuinely unsolved (so we don't oversell). We're
choosing NOT to depend on any of these systems directly — the schema/retrieval ideas they
validate are being hand-implemented instead.

| System | Open source? | Edge payload? | Retrieval | Causal-aware? | Multi-tenant model |
|---|---|---|---|---|---|
| **Graphiti** | Yes (Apache-2.0) | Yes — bi-temporal validity, provenance, facts | Vector + BM25 + graph traversal | No (temporal, not causal) | `group_id`, "group graphs" |
| **cognee** | Yes (Apache-2.0) | Yes — LLM-typed relations, provenance | Vector + graph traversal | No | Permission-check pipeline stage |
| **HippoRAG / HippoRAG2** | Yes (research-grade) | Triples only | Personalized PageRank over dual-node graph | No | Not a memory service |
| **FalkorDB** | Source-available (unverified redistribution terms) | Whatever schema added | Sparse-matrix Cypher engine | No | Whatever built on top |
| **Letta (MemGPT)** | Source-available | No — JSON memory blocks | Context-window paging | No | Shared blocks, last-write-wins risk |

**What's real vs. research-stage:** rich edge payloads with temporal validity, hybrid
vector+lexical+graph retrieval, and namespaced multi-tenancy are all proven ideas — we're
reimplementing proven *patterns*, not unproven ones. Statistical causal discovery over
memory edges is not solved anywhere; we're not attempting it (see Premise 3). Every
cross-vendor benchmark number in this space is self-serving — treat none as fact.

Sources: github.com/getzep/graphiti, github.com/topoteretes/cognee,
github.com/osu-nlp-group/hipporag, falkordb.com, docs.letta.com.

## Competitor Analysis (extended 2026-08-20 — Honcho + graphify)

| System | What's genuinely good | Where it lacks | Where Echo Memory wins |
|---|---|---|---|
| **Honcho** (AGPL-3.0) | Real production infra (Postgres+pgvector, Redis, Docker Compose). "Theory of mind" framing tracks evolving belief about a peer, not static facts. Peer/Session model natively supports multi-agent. Hybrid BM25+vector retrieval validated in production. **Validates our own storage pivot** — same Postgres+pgvector choice, same reasoning (concurrent multi-tenant writes). | Not a graph at all — no edges, no payload, no traversal, no causal typing. AGPL-3.0 copyleft. | Graph structure (v1b, via AGE), causal typing (v1b), multi-hop PPR reasoning (v1b) — on the same proven storage foundation, v1a already running. |
| **graphify** (Apache-2.0, installed locally) | Already solves several open problems: an honest EXTRACTED/INFERRED/AMBIGUOUS audit trail per edge (same spirit as this design's `confidence` enum); hybrid AST+LLM extraction; community detection for organization; incremental `--update` with manifest caching; an MCP server mode already built; NetworkX-backed (BSD, tested PageRank) — **this design now also uses networkx directly for PPR, per Premise 6**; zero-dependency local operation. | Built for point-in-time corpus snapshots, not episodic memory — no bi-temporal edges, no causal typing, no multi-tenant scoping, no session-based ingestion, no statistical retrieval fusion at query time. | Temporal/episodic model, multi-tenancy, causal typing, retrieval fusion. |
| **Graphiti / cognee / HippoRAG / Mem0 / Letta / FalkorDB** | See Landscape table above. | See Landscape table above. | See Landscape table above. |

**Explicit decision:** despite graphify covering real gaps in this plan, the decision is
to **stay fully from-scratch on the memory/graph logic** — graphify's corpus-snapshot
model carries assumptions (file-based, not episodic-memory-based) not worth inheriting.
**Refined after the outside-voice review:** "from scratch" applies to the memory/graph
*logic* (schema, causal typing, tenancy, fusion) — it does not mean re-deriving generic,
already-solved *graph math* like PPR, which is why `networkx` is used directly (Premise
6) rather than hand-rolled and separately validated against the same library.

## Recommended Approach: Staged, Final-Architecture, AGE-Decoupled

### v1a — prove the core recall loop (no AGE, no causal_hint, no PPR)

**Storage:** PostgreSQL (PostgreSQL License), the one canonical database from single-agent
through org-wide — no staged migration on the *storage engine* itself. Nodes, edges, and
the audit log live in **plain Postgres tables** (not an AGE property graph — see Premise
6). Real MVCC gives correct concurrent multi-writer behavior natively.

**Vector search:** **pgvector** (PostgreSQL License) — mature, extremely widely adopted
(including by Honcho), lives in the same database, no separate vector store to sync.

**Lexical search:** Postgres's **native full-text search** (`tsvector`/`ts_rank`,
GIN-indexed, using `plainto_tsquery`/`websearch_to_tsquery` — never raw `to_tsquery` on
user input, per the security review) — built-in, not a third-party dependency.

**Fusion:** Reciprocal Rank Fusion combining pgvector + full-text-search scores only (2
signals). PPR is not part of v1a's fusion — it needs the graph traversal infrastructure
that's deliberately not part of v1a.

**Effort: M.** Smaller than the original combined estimate specifically because AGE,
causal_hint, and PPR — the three most novel and riskiest pieces — are no longer part of
v1a's critical path.

**Primary open risk:** does the invocation mechanism (agents actually calling the MCP
tools reliably) work at all? Spiked first, before other v1a work (Next Steps #1).
**Secondary risk:** entity resolution quality (unchanged from before — see Concrete
Schema).

### v1b — causal typing, graph traversal, multi-hop retrieval (gated on v1a's exit criteria)

**Graph traversal:** **Apache AGE** (Apache-2.0, Apache Software Foundation-governed) added
to the same Postgres instance as a Cypher extension. v1a's plain tables convert to an AGE
property graph at this point — a real, one-time, planned migration (using the versioned
migration tooling from the CEO plan's Section 9 finding), not the kind of unplanned
migration Premise 2 exists to avoid. **Contingent on a spike** (Next Steps) confirming
AGE's maturity/performance; named fallback is hand-rolled traversal over the same plain
tables if it fails — v1a's schema already supports this without change.

**Causal typing:** `causal_hint` classification (see Concrete Schema) added to the edge
schema via migration; classified at ingestion by the same LLM call that extracts
`relation_type`, going forward — **not backfilled onto v1a-era data** (data ingested
during the v1a trial keeps `causal_hint: null`, which is a valid state, not a gap to fix).

**Graph centrality:** **`networkx`'s `personalized_pagerank`** (BSD-licensed) run over the
graph's adjacency structure, pulled via a Cypher query against AGE (or the plain-table
fallback). Not hand-rolled — see Premise 6.

**Fusion:** RRF now combines pgvector + full-text-search + PPR (3 signals).

**Effort: M-L**, contingent on the AGE spike's outcome.

**Primary risk:** Apache AGE's maturity — Cypher-on-Postgres has known rough edges. The
spike is a genuine go/no-go, not a formality.
**Secondary risk:** `causal_hint` classification quality — validated via the eval set,
with the explicit caveat that 5-10 items gives directional confidence only (needs a real
precision/recall threshold before the accepted `contradicts`-surfacing feature enables —
see the CEO plan).

**Scaling story for PPR:** full graph power iteration on every query has no scaling story
as the edge table grows indefinitely. v1b sets an explicit latency budget (target: under
200ms for a graph under 10K edges — realistic for a single user's memory over months) and
a stated fallback if that budget is blown: cap the graph size, or recompute PPR on a
schedule rather than per-query.

**Embedding model:** an external API call (provider TBD — see Open Questions), not a
framework dependency — swappable without touching the rest of the system. Applies to both
v1a and v1b.

## Concrete Schema

### v1a schema (plain Postgres tables — no AGE)

**Node table:**
```
node {
  id, name: string                # canonical entity name
  type: string                    # e.g. "tool", "decision", "preference", "person"
  group_id: string                # tenancy scope, same as edge
  created_at, updated_at: timestamp
  aliases: [string]                # alternate mentions resolved to this node, see below
}
```

**Entity resolution (v1a procedure — the most load-bearing piece of v1a, addressed
explicitly):** on each `write_episode` call, for every entity the extraction step names,
resolve against existing nodes in the same `group_id` in two passes: (1) exact/near-exact
string match against `node.name` and `node.aliases` (cheap, deterministic); (2) if no
match, a single LLM confirmation call — "is this new mention referring to the same entity
as [candidate node], or a new one?" — only for candidates surfaced by embedding similarity
above a threshold (avoids an LLM call per mention). No match on either pass creates a new
node. A confirmed match appends the new surface form to `aliases`.

**Edge table:**
```
edge {
  id, source_node_id, target_node_id
  relation_type: string          # semantic type — e.g. "prefers", "decided", "uses"
  fact: string                   # the actual natural-language fact this edge encodes
  confidence: enum                # extracted | inferred | ambiguous — calibration-honest
                                   # label (adapted from graphify's audit-trail pattern,
                                   # not its code) rather than a raw float, since LLM
                                   # self-reported numeric confidence is poorly calibrated
  t_valid, t_invalid: timestamp  # bi-temporal validity
  provenance: {session_id, source_episode_id}
  group_id: string               # tenancy scope, see below
}
```
No `causal_hint` field in v1a — added via migration in v1b (see Recommended Approach).
`access` field is **deferred to v1.1** — no `access` field on v1a/v1b edges.

**Audit log table (v1a):**
```
audit_entry {
  timestamp
  mutation_type: enum       # created | invalidated | fact_superseded | entity_resolved
  affected_edge_ids: [id]   # for fact-level mutations
  affected_node_id: id      # for entity_resolved entries
  before_fact, after_fact: string | null
  session_id: string
  summary: string            # e.g. "invalidated 'uses SQLite' — superseded by 'uses Postgres'"
  resolution_detail: string | null  # for entity_resolved: which pass matched (exact/fuzzy),
                                     # LLM rationale if the fuzzy pass fired
}
```
**Renamed after the outside-voice review:** the mutation type formerly called `merged` is
now `fact_superseded` — "merged" was overloaded across three different concepts in
earlier drafts (entity-node resolution matches, this audit mutation type, and colloquial
"duplicate entity" talk), which risked real confusion during implementation. **New:** an
`entity_resolved` mutation type was added specifically so `echo-memory why` and the v1a
exit criteria (which require measuring entity-resolution correctness — duplicate/bad-merge
rates) have an actual audit trail to read, instead of requiring reconstruction from alias
lists and memory.

Mechanism: since the storage layer is owned directly, every mutation (edge write,
invalidation, supersession, or entity-resolution decision) is wrapped in application code
that also writes an `audit_entry` row in the same Postgres transaction — real ACID
guarantees, not a best-effort wrapper.

**`fact_superseded` trigger (v1a procedure):** fires only when two edges resolve to the
same `(source_node_id, target_node_id, relation_type)` tuple after entity resolution — the
same fact stated twice, not a general "these seem similar" heuristic. The older edge is
invalidated (`t_invalid` set), the newer one's `fact` and `confidence` win, and one
`audit_entry` with `mutation_type: fact_superseded` records both `affected_edge_ids`. No
LLM-judged fuzzy merging of *facts* in v1a — that's a real risk (false merges) explicitly
deferred, not silently dropped. (Entity-node resolution's fuzzy pass, above, is different
and does use LLM confirmation — that's a node-identity decision, not a fact-content
decision.)

**`group_id` naming convention (two tiers in v1a/v1b, org tier in v1.1):**
- Single-agent: `group_id = "user:{user_id}:agent:{agent_id}"` — e.g. `user:ayush:agent:claude-code`
- Multi-agent, same user (shared): `group_id = "user:{user_id}:shared"` — e.g.
  `user:ayush:shared`, read/written by all of that user's agents.
- Org-wide (`org:{org_id}`) is **v1.1**.

### v1b schema additions (via migration, on top of v1a's tables)

**`causal_hint` column added to the edge table:**
```
causal_hint: enum | null   # caused_by | led_to | enabled_by | blocked_by | contradicts | null
```
`relation_type` vs. `causal_hint`: when `causal_hint` is non-null, `relation_type`
describes *what* the fact is (e.g. `"decided"`, `"uses"`), while `causal_hint` captures
*why/how it relates causally* — never `relation_type: "caused"` alongside
`causal_hint: "caused_by"`, which is redundant.

**`causal_hint` classification (v1b procedure):** at ingestion, the same LLM call
extracting `relation_type` also asks: "did the source fact directly cause, enable, or
block the target fact, per what the conversation/session explicitly states — not what you
infer statistically?" Answer one of the five enum values or `null` if associative only.
Example: "switched to Postgres because SQLite couldn't handle concurrent writes" → edge
`{relation_type: "decided", causal_hint: "caused_by", fact: "switched to Postgres due to
SQLite concurrent-write limits"}` — `relation_type` says what happened, `causal_hint` says
why. "also considered using MongoDB" → `{relation_type: "considered", causal_hint: null}`.

**Node/edge conversion to an AGE property graph** happens as part of v1b setup, via the
versioned migration tool (CEO plan finding 9A) — a planned, tested migration, not an
unplanned one.

### Configuration (server startup, per agent — answers "how is scope actually set")

`group_id` is an internal identifier, never typed or constructed by the calling agent.
Each agent's MCP client config (e.g. Claude Code's `.mcp.json`) launches its own Echo
Memory server process with environment variables identifying it:
```
ECHO_MEMORY_USER_ID=<user>              # required
ECHO_MEMORY_AGENT_ID=<agent, e.g. claude-code | cursor>  # required
ECHO_MEMORY_DATABASE_URL=postgres://...  # shared across all of a user's agents
```
Multiple agents (Claude Code, Cursor, etc.) run separate server processes with different
`ECHO_MEMORY_AGENT_ID` values but the same `ECHO_MEMORY_DATABASE_URL` — same underlying
Postgres data, different identity per process. `ECHO_MEMORY_ORG_ID` is added in v1.1.

### MCP tool contract (minimal, stable across v1a → v1b)

```
write_episode(scope: "solo" | "shared", session_id, text) -> {edges_created: [id]} | {error: string}
query_memory(scope: "solo" | "shared", query, top_k: int = 10, max 100) -> {facts: [{fact, confidence, causal_hint, provenance}]} | {error: string}
get_audit_log(scope: "solo" | "shared", since?: ISO8601 timestamp) -> {entries: [audit_entry]} | {error: string}
```
`scope` replaces a raw `group_id` parameter — the agent picks "solo" (this agent's own
private memory, `user:{USER_ID}:agent:{AGENT_ID}`) or "shared" (the pool all of this
user's agents read/write, `user:{USER_ID}:shared`); the server resolves the actual
`group_id` internally from its own startup config, per the naming convention above. This
removes any risk of an agent typo'ing or hand-constructing its way into the wrong scope.
v1.1 adds `scope: "org"`, gated by `ECHO_MEMORY_ORG_ID` being configured and the ACL
layer landing.

All three tools return a typed `{error: string}` object on failure rather than raising —
`top_k` defaults to 10, capped at 100; `since` is an ISO8601 timestamp, entries at or
after it. In v1a, `causal_hint` in `query_memory`'s response is always `null` (the field
exists in the contract from the start so v1b doesn't need a breaking API change — it's
just always empty until v1b populates it).

## Open Questions

- **Does the invocation mechanism even work?** (Premise 7) — does Claude Code/Cursor
  reliably call `write_episode`/`query_memory` at natural checkpoints without being
  explicitly told to, or does this require constant manual prompting that undermines the
  whole "reduces re-explaining" value prop? Spiked first, before any other v1a work.
  **Confirmed after the eng-review outside voice:** whether an agent *chooses* to call a
  tool isn't meaningfully CI-testable (it depends on the calling model's behavior, not
  code under this project's control) — PR0's spike plus the v1a trial's week of continuous
  real usage is the accepted signal, not ongoing automated coverage. Revisit only if
  invocation drift is actually observed later.
- **Apache AGE maturity/performance** — v1b-only now (decoupled from v1a per Premise 6).
  Resolved by a spike before v1b work starts, with a named fallback (hand-rolled traversal
  over the same plain tables v1a already uses) if it doesn't hold up.
- Embedding model/provider choice — not yet decided; affects cost and portability.
- RRF fusion weights (pgvector vs. full-text-search, and later vs. PPR) need tuning
  against real queries.
- **`causal_hint` precision/recall threshold** — the eval set gives directional confidence
  only at 5-10 items; a real number is needed before the `contradicts`-surfacing feature
  (accepted in the CEO plan) is safe to enable, not just "check the eval set."
- ~~License choice~~ — resolved: **Apache-2.0**, matching the ecosystem this project's
  dependencies are governed under (Apache AGE, Graphiti, cognee) and offering an explicit
  patent grant, valuable for infrastructure meant to be built on.
- Hosting story for a future managed offering (v1.1) — which providers support both
  pgvector *and* AGE together is worth checking before promising a hosted path.

## Success Criteria

### v1a
1. The invocation-mechanism spike (Open Questions) shows agents actually call the MCP
   tools at natural checkpoints without constant manual prompting — this is a gate before
   the rest of v1a is worth building, not just a nice-to-have signal.
2. Postgres+pgvector store running (via Docker Compose — no AGE needed for v1a), ingesting
   real session data, including at least one real case where entity resolution correctly
   matches a new mention to an existing node — logged as an `entity_resolved` audit entry,
   not just observed anecdotally.
3. Two working `group_id` scopes demonstrated: single-agent and multi-agent-shared-user.
4. One concrete example where 2-signal hybrid retrieval (pgvector + full-text via RRF)
   answers a real question from your own memory better than either signal alone.
5. An append-only audit log entry for at least one fact mutation and at least one entity
   resolution decision, human-readable enough to answer "why did this happen."
6. A rough cost and latency baseline for a real ingestion + query cycle.
7. **v1a → v1b exit criteria** (over a trial of real cross-tool usage, capped at 3 weeks
   total — this is a hard cap, not indefinitely extendable): at least 3 real instances
   where a recalled fact saved re-explaining something to a different tool; at most 1
   duplicate node created by entity resolution; zero cases of two distinct entities
   incorrectly merged into one node. If the bars aren't met, revisit the recall mechanism
   itself before starting any v1b work.

### v1b (gated on v1a's exit criteria being met)
1. Apache AGE spike passes (or the plain-table fallback is confirmed sufficient).
2. A small eval set (5-10 real facts) manually checked for `causal_hint` classification
   quality, with a concrete precision/recall threshold set (not just "check the eval
   set") before enabling `contradicts` surfacing.
3. PPR (via `networkx`) validated for correctness on a small test graph (using a trusted
   library directly means this is closer to "confirm it's wired correctly" than "confirm
   our reimplementation is correct").
4. One concrete example where 3-signal hybrid retrieval (adding PPR) answers a real
   multi-hop question that 2-signal v1a retrieval missed or ranked poorly.

## Distribution Plan

**v1a:** A single-command **Docker Compose** setup bundling Postgres + pgvector (no AGE
yet — v1a doesn't need it) plus a thin process implementing the MCP server. Simpler than
originally planned, since AGE is no longer part of v1a's footprint.
**v1b:** The same Docker Compose setup gains the AGE extension; existing v1a data
converts via the versioned migration tool.
**v1.1:** Hosted/managed option and org-onboarding, once identity/auth is resolved and the
managed-Postgres-provider question (Open Questions) is answered.
Open-source repository, Apache-2.0 licensed: github.com/ayushcodes10/echo-mem.

## Implementation Language

**Python** — chosen during /plan-eng-review because `networkx` (the PPR library, per
Premise 6) is Python-native, avoiding a cross-language bridge. Mature `pgvector-python`
and `psycopg` clients; Alembic for versioned migrations; the official MCP Python SDK.

## PR Plan (dependency-ordered — this repo is open source, so small independently
reviewable PRs matter more than a single large landing)

| PR | Scope | Modules | Depends on |
|---|---|---|---|
| PR0 | Invocation-mechanism spike (does Claude Code/Cursor actually call MCP tools reliably?) — throwaway script/findings, not merged as product code | — | — |
| PR1 | Repo scaffold, CI (lint+test on push), Postgres+pgvector Docker Compose, migration tooling (Alembic), schema (node/edge/audit_entry tables + pgvector ANN index + GIN full-text index) | `infra/`, `migrations/` | PR0 passes |
| PR2 (Lane A) | Entity resolution + `write_episode`, connection pooling, structured server-side logging, input-size cap | `ingestion/`, `db/` | PR1 |
| PR3 (Lane B) | Retrieval (pgvector+FTS+RRF, 2 signals) + `query_memory`, `top_k` cap, `plainto_tsquery`/`websearch_to_tsquery` (never raw `to_tsquery`) | `retrieval/` | PR1 |
| PR4 | Audit log wiring (`entity_resolved` + `fact_superseded` entries, same-transaction writes) + `get_audit_log` | `audit/` | PR2 |
| PR5 | MCP server packaging: wire all 3 tools together, localhost-bound only, typed `{error}` contract end-to-end | `mcp-server/` | PR2, PR3, PR4 |
| PR-FF1 | `echo-memory why`/`export` CLI | `cli/` | PR4 |
| *(v1a exit-criteria trial begins — real usage against the CEO plan's gated window, no new code)* | | | PR5 **and** PR-FF1 |
| PR-FF2 | Onboarding nudge + context digest | `ingestion/`, `retrieval/` (additive) | PR5 |
| PR-B1 (v1b, gated on v1a exit criteria) | AGE spike; if it passes, migrate v1a's tables to an AGE property graph via Alembic, **preserving a stable mapping from v1a's plain-table IDs to AGE's internal `graphid` scheme** so `audit_entry` rows written during the v1a trial stay resolvable — required, not optional, since `echo-memory why` must keep working for the exact data the exit criteria were measured against | `migrations/`, `graph/` | v1a exit criteria met |
| PR-B2 (Lane A) | `causal_hint` classification at ingestion | `ingestion/` | PR-B1 |
| PR-B3 (Lane B) | PPR via `networkx.personalized_pagerank`, extend RRF to 3 signals | `retrieval/`, `graph/` | PR-B1 |
| PR-B4 | `contradicts` surfacing (query-time + local notification), gated on the causal_hint quality threshold | `retrieval/`, `notifications/` | PR-B2, PR-B3 |
| PR-1.1-* (v1.1) | Identity/auth → ACL enforcement → sensitive-data redaction, in that order | `auth/`, `db/`, `ingestion/` | v1b shipped |

**Parallel lanes:** PR2 ∥ PR3 once PR1 lands (PR1 establishes the shared `db/`
connection-pooling utility once, so PR2/PR3 only import it). PR-B2 ∥ PR-B3 once PR-B1
lands, same reasoning — no shared modules between them.

CI (basic: lint + test on push) is set up in PR1, not deferred — cheap now, catches
regressions immediately as the rest of the PRs land.
