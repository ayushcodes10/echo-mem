"""Entity resolution (see the design doc's Concrete Schema "Entity resolution"
section). Runs three ways: exact/near-exact match, embedding-similarity match
above a high threshold, or genuinely ambiguous (deferred to the calling agent
via write_episode's ambiguous_entities/entity_resolutions round-trip). The
server never calls an LLM here; see the MCP tool contract's architecture
pivot note.

KNOWN v1a LIMITATION: only checks each entity against nodes already in the
database, not against other entities in the same write_episode call. Two
new, near-duplicate names in one call (e.g. "Postgres" and "PostgreSQL",
neither existing yet) both resolve as new and create two nodes; there's no
in-batch embedding available to compare against until write_episode's later
node-creation step. A later call mentioning either name will still resolve
correctly against whichever node was created first. Documented, not silently
dropped; see MATHS.local.md's open questions."""

import json
from dataclasses import dataclass, field

from echo_memory.infra.db import GRAPH_NAME as GRAPH

LOW_THRESHOLD = 0.75
HIGH_THRESHOLD = 0.92


@dataclass
class Candidate:
    node_id: str
    name: str
    similarity: float


@dataclass
class Ambiguous:
    mention: str
    candidates: list[Candidate]


@dataclass
class ResolutionOutcome:
    # mention -> node graphid (as text)
    resolved: dict[str, str] = field(default_factory=dict)
    ambiguous: list[Ambiguous] = field(default_factory=list)
    # entity_resolved audit rows to write: {node_id, resolution_detail}
    audit_events: list[dict] = field(default_factory=list)
    # mentions determined to be brand new entities, no audit trail needed
    new_entities: set[str] = field(default_factory=set)


def _exact_match(conn, group_id: str, name: str) -> tuple[str, str] | None:
    """Case-insensitive match against node.name or any alias. Returns
    (graphid, matched_name) or None."""
    params = json.dumps({"gid": group_id, "name": name})

    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node {{group_id: $gid}})
            WHERE toLower(n.name) = toLower($name)
            RETURN id(n), n.name
            LIMIT 1
        $$, %s) AS (node_id agtype, name agtype)""",
        (params,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH (n:Node {{group_id: $gid}})
                UNWIND n.aliases AS alias
                WITH n, alias
                WHERE toLower(alias) = toLower($name)
                RETURN id(n), n.name
                LIMIT 1
            $$, %s) AS (node_id agtype, name agtype)""",
            (params,),
        ).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1]).strip('"')


def _fuzzy_candidates(conn, group_id: str, embedding: list[float], limit: int = 5) -> list[Candidate]:
    rows = conn.execute(
        """
        SELECT ne.node_id::text, 1 - (ne.embedding <=> %s::vector) AS similarity
        FROM public.node_embedding ne
        WHERE ne.group_id = %s
        ORDER BY ne.embedding <=> %s::vector
        LIMIT %s
        """,
        (embedding, group_id, embedding, limit),
    ).fetchall()
    if not rows:
        return []

    node_ids = [node_id for node_id, _ in rows]
    similarity_by_id = {node_id: float(similarity) for node_id, similarity in rows}

    name_rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            UNWIND $ids AS nid
            MATCH (n:Node) WHERE id(n) = nid
            RETURN id(n), n.name
        $$, %s) AS (node_id agtype, name agtype)""",
        (json.dumps({"ids": [int(nid) for nid in node_ids]}),),
    ).fetchall()
    name_by_id = {str(node_id): str(name).strip('"') for node_id, name in name_rows}

    return [
        Candidate(node_id=nid, name=name_by_id.get(nid, "?"), similarity=similarity_by_id[nid])
        for nid in node_ids
    ]


def resolve_entities(
    conn,
    group_id: str,
    entities: list[dict],
    resolutions: dict[str, dict],
    embedder,
    low_threshold: float = LOW_THRESHOLD,
    high_threshold: float = HIGH_THRESHOLD,
) -> ResolutionOutcome:
    outcome = ResolutionOutcome()

    for entity in entities:
        name = entity["name"]

        if name in resolutions:
            resolution = resolutions[name]
            resolved_to = resolution["resolved_to"]
            if resolved_to == "new":
                outcome.new_entities.add(name)
            else:
                outcome.resolved[name] = resolved_to
                outcome.audit_events.append(
                    {
                        "node_id": resolved_to,
                        "resolution_detail": "agent-confirmed fuzzy match"
                        + (f": {resolution['rationale']}" if resolution.get("rationale") else ""),
                        "append_alias": name,
                    }
                )
            continue

        exact = _exact_match(conn, group_id, name)
        if exact is not None:
            node_id, _matched_name = exact
            outcome.resolved[name] = node_id
            outcome.audit_events.append({"node_id": node_id, "resolution_detail": "exact match"})
            continue

        embedding = embedder.embed(name)
        candidates = _fuzzy_candidates(conn, group_id, embedding)
        best = candidates[0] if candidates else None

        if best is not None and best.similarity >= high_threshold:
            outcome.resolved[name] = best.node_id
            outcome.audit_events.append(
                {
                    "node_id": best.node_id,
                    "resolution_detail": f"fuzzy match, similarity={best.similarity:.3f}",
                    "append_alias": name,
                }
            )
        elif best is not None and best.similarity >= low_threshold:
            outcome.ambiguous.append(Ambiguous(mention=name, candidates=candidates))
        else:
            outcome.new_entities.add(name)

    return outcome
