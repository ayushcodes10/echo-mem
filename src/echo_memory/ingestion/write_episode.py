"""write_episode: storage, resolution, and retrieval only, never inference
(see the design doc's MCP tool contract architecture pivot). Entities/facts
arrive already extracted by the calling agent."""

import json
import time
import uuid

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.logging import get_logger, log_write_episode
from echo_memory.ingestion.resolution import resolve_entities

MAX_ENTITIES = 50
MAX_FACTS = 200
MAX_STRING_LEN = 4000
VALID_CONFIDENCE = {"extracted", "inferred", "ambiguous"}

_logger = get_logger("write_episode")


class ValidationError(Exception):
    pass


def _validate(entities: list[dict], facts: list[dict]) -> None:
    if len(entities) > MAX_ENTITIES:
        raise ValidationError(f"too many entities: {len(entities)} > {MAX_ENTITIES}")
    if len(facts) > MAX_FACTS:
        raise ValidationError(f"too many facts: {len(facts)} > {MAX_FACTS}")

    entity_names = set()
    for entity in entities:
        name = entity.get("name", "")
        if not name or len(name) > MAX_STRING_LEN:
            raise ValidationError(f"invalid entity name: {name[:80]!r}")
        entity_names.add(name)

    for fact in facts:
        if len(fact.get("fact", "")) > MAX_STRING_LEN:
            raise ValidationError("fact text too long")
        if fact.get("confidence") not in VALID_CONFIDENCE:
            raise ValidationError(f"invalid confidence: {fact.get('confidence')!r}")
        if fact.get("source") not in entity_names:
            raise ValidationError(f"fact source {fact.get('source')!r} not in entities")
        if fact.get("target") not in entity_names:
            raise ValidationError(f"fact target {fact.get('target')!r} not in entities")


def _create_node(conn, group_id: str, name: str, type_: str, embedder) -> str:
    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            CREATE (n:Node {{name: $name, type: $type, group_id: $gid, aliases: []}})
            RETURN id(n)
        $$, %s) AS (node_id agtype)""",
        (json.dumps({"name": name, "type": type_, "gid": group_id}),),
    ).fetchone()
    node_id = str(row[0])
    embedding = embedder.embed(name)
    conn.execute(
        "INSERT INTO public.node_embedding (node_id, group_id, embedding) VALUES (%s::graphid, %s, %s)",
        (node_id, group_id, embedding),
    )
    return node_id


def _append_alias(conn, node_id: str, alias: str) -> None:
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE id(n) = $nid AND NOT $alias IN n.aliases
            SET n.aliases = n.aliases + [$alias]
        $$, %s) AS (r agtype)""",
        (json.dumps({"nid": int(node_id), "alias": alias}),),
    )


def _find_active_edge(conn, group_id: str, source_id: str, target_id: str, relation_type: str) -> str | None:
    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (a)-[e:FACT {{relation_type: $rel, group_id: $gid}}]->(b)
            WHERE id(a) = $sid AND id(b) = $tid AND e.t_invalid IS NULL
            RETURN id(e)
            LIMIT 1
        $$, %s) AS (edge_id agtype)""",
        (
            json.dumps(
                {"rel": relation_type, "gid": group_id, "sid": int(source_id), "tid": int(target_id)}
            ),
        ),
    ).fetchone()
    return str(row[0]) if row else None


def _invalidate_edge(conn, edge_id: str, t_invalid: int) -> None:
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->() WHERE id(e) = $eid
            SET e.t_invalid = $t_invalid
        $$, %s) AS (r agtype)""",
        (json.dumps({"eid": int(edge_id), "t_invalid": t_invalid}),),
    )


def _create_edge(
    conn,
    group_id: str,
    source_id: str,
    target_id: str,
    fact: dict,
    session_id: str,
    episode_id: str,
    t_valid: int,
    embedder,
) -> str:
    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (a), (b) WHERE id(a) = $sid AND id(b) = $tid
            CREATE (a)-[e:FACT {{
                relation_type: $rel, fact: $fact, confidence: $confidence,
                t_valid: $t_valid, t_invalid: null, group_id: $gid,
                provenance: {{session_id: $session_id, source_episode_id: $episode_id}}
            }}]->(b)
            RETURN id(e)
        $$, %s) AS (edge_id agtype)""",
        (
            json.dumps(
                {
                    "sid": int(source_id),
                    "tid": int(target_id),
                    "rel": fact["relation_type"],
                    "fact": fact["fact"],
                    "confidence": fact["confidence"],
                    "t_valid": t_valid,
                    "gid": group_id,
                    "session_id": session_id,
                    "episode_id": episode_id,
                }
            ),
        ),
    ).fetchone()
    edge_id = str(row[0])
    embedding = embedder.embed(fact["fact"])
    conn.execute(
        "INSERT INTO public.fact_embedding (edge_id, group_id, embedding) VALUES (%s::graphid, %s, %s)",
        (edge_id, group_id, embedding),
    )
    return edge_id


def _write_audit_entry(conn, group_id: str, session_id: str, **fields) -> None:
    columns = ["group_id", "session_id"] + list(fields.keys())
    values = [group_id, session_id] + list(fields.values())
    placeholders = ", ".join(["%s"] * len(values))
    conn.execute(
        f"INSERT INTO public.audit_entry ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )


def write_episode(
    conn,
    group_id: str,
    session_id: str,
    entities: list[dict],
    facts: list[dict],
    resolutions: dict[str, dict] | None,
    embedder,
) -> dict:
    resolutions = resolutions or {}
    start = time.perf_counter()

    try:
        _validate(entities, facts)
    except ValidationError as e:
        log_write_episode(
            _logger, group_id, session_id, len(entities), len(facts), 0, 0,
            (time.perf_counter() - start) * 1000, error=str(e),
        )
        return {"error": str(e)}

    episode_id = str(uuid.uuid4())
    now = int(time.time())
    edges_created: list[str] = []

    with conn.transaction():
        outcome = resolve_entities(conn, group_id, entities, resolutions, embedder)

        entities_by_name = {e["name"]: e for e in entities}
        name_to_node_id = dict(outcome.resolved)
        for name in outcome.new_entities:
            entity = entities_by_name[name]
            name_to_node_id[name] = _create_node(
                conn, group_id, entity["name"], entity["type"], embedder
            )

        for event in outcome.audit_events:
            _write_audit_entry(
                conn,
                group_id,
                session_id,
                mutation_type="entity_resolved",
                affected_node_id=event["node_id"],
                resolution_detail=event["resolution_detail"],
                summary=f"entity resolved: {event['resolution_detail']}",
            )
            if "append_alias" in event:
                _append_alias(conn, event["node_id"], event["append_alias"])

        ambiguous_mentions = {a.mention for a in outcome.ambiguous}
        ready_facts = [
            f
            for f in facts
            if f["source"] not in ambiguous_mentions and f["target"] not in ambiguous_mentions
        ]

        for fact in ready_facts:
            source_id = name_to_node_id[fact["source"]]
            target_id = name_to_node_id[fact["target"]]
            existing_edge_id = _find_active_edge(
                conn, group_id, source_id, target_id, fact["relation_type"]
            )

            new_edge_id = _create_edge(
                conn, group_id, source_id, target_id, fact, session_id, episode_id, now, embedder
            )
            edges_created.append(new_edge_id)

            if existing_edge_id is not None:
                _invalidate_edge(conn, existing_edge_id, now)
                _write_audit_entry(
                    conn,
                    group_id,
                    session_id,
                    mutation_type="fact_superseded",
                    affected_edge_ids=[existing_edge_id, new_edge_id],
                    summary=f"superseded by: {fact['fact']}",
                )
            else:
                _write_audit_entry(
                    conn,
                    group_id,
                    session_id,
                    mutation_type="created",
                    affected_edge_ids=[new_edge_id],
                    summary=f"created: {fact['fact']}",
                )

    log_write_episode(
        _logger, group_id, session_id, len(entities), len(facts),
        len(edges_created), len(outcome.ambiguous), (time.perf_counter() - start) * 1000,
    )
    return {
        "edges_created": edges_created,
        "ambiguous_entities": [
            {
                "mention": a.mention,
                "candidates": [
                    {"node_id": c.node_id, "name": c.name, "similarity": c.similarity}
                    for c in a.candidates
                ],
            }
            for a in outcome.ambiguous
        ],
    }
