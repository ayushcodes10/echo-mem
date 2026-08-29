"""python -m echo_memory.server: wires write_episode, query_memory, and
get_audit_log into one MCP server (see the design doc's MCP tool contract).
Runs over stdio by default (mcp.server.mcpserver's MCPServer.run default),
not a network listener at all, let alone one bound beyond localhost; see
the design doc's Constraints ("v1 is single-user, local-only")."""

import psycopg
from mcp.server.mcpserver import MCPServer

from echo_memory.audit.get_audit_log import get_audit_log as _get_audit_log
from echo_memory.infra.config import Config, ConfigError, load_config
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.logging import configure_logging, get_logger
from echo_memory.infra.pool import make_pool
from echo_memory.infra.project import UNKNOWN as UNKNOWN_AGENT
from echo_memory.ingestion import bootstrap as bootstrap_mod
from echo_memory.ingestion import capture
from echo_memory.ingestion.embeddings import Embedder, LocalEmbedder
from echo_memory.ingestion.write_episode import write_episode as _write_episode
from echo_memory.retrieval.query_memory import query_memory as _query_memory
from echo_memory.trial import observations as _observations

server = MCPServer(
    name="echo-memory",
    instructions=(
        "Persistent memory across sessions and tools, backed by your own local "
        "database. Use it proactively, without being asked - don't wait for a "
        "natural stopping point. Call write_episode IN THE SAME TURN whenever "
        "any of these happen: the user states a decision (\"we're using X\", "
        "\"X only deploys from branch Y\"), corrects something you said or did "
        "(\"actually, X not Y\"), states a preference, or says anything like "
        "\"remember this\"/\"for future reference\"/\"don't do that again\". If "
        "you notice one of these mid-task, call write_episode right then, not "
        "batched up at the end. Skip only genuinely throwaway exchanges (typo "
        "fixes, one-off questions with no lasting relevance) - the cost of a "
        "missed memory is higher than the cost of one extra call. Call "
        "query_memory at the start of a session, and any other time recalling "
        "prior context would save the user from re-explaining something they "
        "likely already told a different tool or a past session - check here "
        "before asking them to repeat themselves."
    ),
)


class ServerState:
    """Not module-level globals directly: keeps startup() testable without
    mutating process-wide state that other tests might also touch."""

    config: Config
    pool: object
    embedder: Embedder


_state = ServerState()


def startup(config: Config | None = None, embedder: Embedder | None = None) -> None:
    # Structured logs to stderr. stdout is the MCP protocol channel.
    configure_logging()
    _state.config = config or load_config()
    _state.pool = make_pool(_state.config.database_url)
    _state.embedder = embedder or LocalEmbedder()


@server.tool()
def write_episode(
    scope: str,
    session_id: str,
    entities: list[dict],
    facts: list[dict],
    entity_resolutions: dict | None = None,
) -> dict:
    """Record something worth remembering later: a decision, a correction,
    a stated preference, or context that would otherwise have to be
    re-explained to a different tool or a future session. Call this
    proactively and immediately when you notice one of these - don't wait
    to be asked, and don't batch it up for later in the conversation. The
    cost of a missed memory (re-explaining something later) is higher than
    the cost of one extra call.

    You (the calling agent) extract entities/facts yourself - this server
    never calls an LLM. Exact shape, every key required unless marked
    optional:

    entities: [{"name": "Postgres", "type": "tool"}, ...]
      - name: non-empty string, unique per entity in this call
      - type: any short string describing what kind of thing this is
        (e.g. "tool", "person", "decision", "preference") - your choice,
        not a fixed enum

    facts: [{"source": "Decision", "target": "Postgres", "relation_type": "uses",
             "fact": "decided to use Postgres for storage", "confidence": "extracted"}, ...]
      - source/target: must each exactly match a "name" in entities above
      - relation_type: any short string describing the relationship
        (e.g. "uses", "prefers", "caused_by") - your choice, not a fixed enum
      - fact: the actual sentence to remember, plain text
      - confidence: MUST be exactly one of "extracted" (directly stated),
        "inferred" (you deduced it), or "ambiguous" (uncertain) - any other
        value, including numbers or omitting it, is rejected

    entity_resolutions (optional): only needed when a previous call
    returned ambiguous_entities and you're now confirming which candidate
    a mention refers to, or that it's new: {"mention name": {"resolved_to":
    "<node_id from ambiguous_entities>" | "new"}}. Omit entirely on a call
    with no prior ambiguity to resolve.

    Example call:
    write_episode(scope="solo", session_id="sess-1",
      entities=[{"name": "Postgres", "type": "tool"}, {"name": "Decision", "type": "decision"}],
      facts=[{"source": "Decision", "target": "Postgres", "relation_type": "uses",
              "fact": "decided to use Postgres for storage", "confidence": "extracted"}])
    """
    try:
        group_id = _state.config.group_id(scope)
    except ConfigError as e:
        return {"error": str(e)}
    try:
        with _state.pool.connection() as conn:
            return _write_episode(
                conn, group_id, session_id, entities, facts, entity_resolutions, _state.embedder,
                project=_state.config.project, agent_id=_state.config.agent_id,
            )
    except psycopg.OperationalError as e:
        return _operational_error(e)


@server.tool()
def query_memory(scope: str, query: str | None = None, top_k: int = 10, digest: bool = False) -> dict:
    """Recall prior facts relevant to query, from this agent's own memory
    (scope="solo") or the pool shared across this user's agents
    (scope="shared"). Call this at session start, and any other time
    recalling prior context would save the user from re-explaining
    something - check here before asking them to repeat themselves or
    guessing at context you don't have.

    digest=True ignores query and returns the most recently written active
    facts instead, as an opt-in "catch me up" convenience; call it
    explicitly at session start if you want one, it's never automatic.

    A pending_ingest field appears when memory files have been written that
    the graph hasn't heard about yet. Read each listed file and call
    write_episode with the entities and facts it states, then mark it done
    with `echo-memory pending --done <path>`. The queue exists because
    extraction needs a model and this server never calls one."""
    try:
        group_id = _state.config.group_id(scope)
    except ConfigError as e:
        return {"error": str(e)}
    try:
        with _state.pool.connection() as conn:
            result = _query_memory(conn, group_id, query, top_k, _state.embedder, digest=digest)
            _bootstrap_once(conn)
            queued = capture.pending(conn)
            if queued:
                result["pending_ingest"] = {
                    "count": len(queued),
                    "files": [{"path": q["path"], "project": q["project"]} for q in queued[:10]],
                    "instruction": (
                        "These memory files were written but never recorded as facts. Read "
                        "each one and call write_episode with what it states, then run "
                        "`echo-memory pending --done <path>` for each."
                    ),
                }
            return result
    except psycopg.OperationalError as e:
        return _operational_error(e)


_logger = get_logger("server")


def _operational_error(e: psycopg.OperationalError) -> dict:
    """Turn a database outage into the typed {"error"} shape every tool
    already uses for ConfigError.

    Deliberately narrow. psycopg.OperationalError covers what is genuinely
    operational - connection lost, server down, and PoolTimeout, which is a
    subclass - while ProgrammingError and IntegrityError are NOT subclasses and
    still propagate. That split matters: swallowing a bad query or a violated
    constraint into a polite message would hide a real bug behind an outage
    story, which is the over-catching this exists to avoid.

    The agent gets something it can act on ("the database is unreachable, tell
    the user") instead of a stack trace it can only relay."""
    _logger.warning("database_unavailable", extra={"error_type": type(e).__name__})
    return {"error": f"memory database unavailable: {e}"}


def _bootstrap_once(conn) -> None:
    """First initialisation sweeps the machine for work that already exists.

    A fresh store is empty, but the machine it runs on usually isn't: months of
    decisions already sit in per-project memory files, gstack learnings and
    CLAUDE.md files. Waiting for new sessions to slowly refill the graph throws
    all of that away and makes the user re-explain what they already wrote down.

    Runs at most once (guarded by bootstrap_state), and never fails a query:
    recall is the caller's actual request, and a discovery problem has no
    business breaking it."""
    try:
        if bootstrap_mod.has_run(conn):
            return
        result = bootstrap_mod.run(conn)
        _logger.info(
            "bootstrap_discovered",
            extra={"found": result["found"], "queued": result["queued"]},
        )
    except Exception as e:  # noqa: BLE001 - see docstring: never fail a query
        _logger.warning("bootstrap_failed", extra={"error": str(e)})


def _author_of(conn, group_id: str, fact_id: str) -> str | None:
    """The `agent_id` on a fact edge, or None if no such fact is in this scope.

    Scoped by group_id on purpose: a fact_id from another tenant must not be
    citable as evidence here, and an unscoped lookup would let one."""
    try:
        edge_id = int(fact_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->()
            WHERE id(e) = {edge_id} AND e.group_id = '{group_id}'
            RETURN e.agent_id
        $$) AS (agent_id agtype)"""
    ).fetchone()
    return str(row[0]).strip('"') if row and row[0] is not None else None


@server.tool()
def record_recall_save(
    scope: str,
    fact_id: str,
    note: str,
    recalled_by: str | None = None,
) -> dict:
    """Record that a fact you recalled from memory saved the user from
    re-explaining something to you.

    Call this IN THE SAME TURN, the moment it happens. The trigger is
    concrete: you called query_memory (or read a memory-derived fact), it
    answered something the user would otherwise have had to tell you again,
    and the fact was originally written by a DIFFERENT tool or a past session.

    That last part is the whole point, and it is why this takes `fact_id`
    rather than a `written_by` string. Pass the `fact_id` of the fact that
    helped - every query_memory result carries one. The server reads that
    edge's own `agent_id` and uses it as `written_by`; the caller does not get
    to assert who wrote a fact.

    Until 2026-08-29 `written_by` was free text supplied by the caller. Nothing
    checked the fact existed, so the number gating v1a was a string typed by
    the model being graded. A fact_id is checkable, so the reading is
    admissible.

    recalled_by is you, defaulting to this server's own agent id. If the fact's
    author and you are the same tool, the save is still recorded but does not
    count toward the trial's bar - recalling your own note from ten minutes ago
    is not the thing being measured.

    note should be one sentence naming what it saved re-explaining, written so
    it still makes sense read cold in six months. Recording the identical note
    twice is a no-op, so a retry after an error is safe.

    Do NOT call this speculatively, for a fact you wrote this session, or
    because a recall was merely interesting. It is evidence for a gate that
    decides real build work; an inflated count is worse than an empty one."""
    try:
        group_id = _state.config.group_id(scope)
    except ConfigError as e:
        return {"error": str(e)}

    recalled_by = recalled_by or _state.config.agent_id
    try:
        with _state.pool.connection() as conn:
            written_by = _author_of(conn, group_id, fact_id)
            if written_by is None:
                return {"error": (
                    f"no fact {fact_id} in this scope - pass the fact_id from a "
                    "query_memory result, not a remembered one"
                )}
            if written_by == UNKNOWN_AGENT:
                return {"error": (
                    f"fact {fact_id} predates agent attribution (agent_id is "
                    f"'{UNKNOWN_AGENT}'), so it cannot evidence a cross-tool save. "
                    "Run `alembic upgrade head` to backfill these."
                )}
            try:
                recorded = _observations.record(
                    conn, group_id, _observations.RECALL_SAVE, note,
                    written_by=written_by, recalled_by=recalled_by,
                )
            except _observations.TrialError as e:
                return {"error": str(e)}
            counts = _observations.counts(conn, [group_id])
    except psycopg.OperationalError as e:
        return _operational_error(e)

    cross_tool = written_by != recalled_by
    _logger.info(
        "recall_save_recorded",
        extra={
            "observation_id": recorded["id"], "newly_recorded": recorded["created"],
            "written_by": written_by, "recalled_by": recalled_by,
            "cross_tool": cross_tool, "group_id": group_id,
        },
    )
    result = {
        "recorded": True,
        "observation_id": recorded["id"],
        "already_recorded": not recorded["created"],
        "counts_toward_gate": cross_tool,
        "cross_tool_saves": counts["cross_tool_saves"],
        "required": _observations.REQUIRED_SAVES,
    }
    if not cross_tool:
        result["note"] = (
            f"Recorded, but {written_by} both wrote and recalled this, so it does not count "
            "toward the trial's cross-tool bar."
        )
    return result


@server.tool()
def get_audit_log(scope: str, since: str | None = None) -> dict:
    """Human-readable audit trail: what was written, invalidated, superseded,
    or resolved, and why. since is an ISO8601 timestamp; entries at or after
    it, chronologically ordered."""
    try:
        group_id = _state.config.group_id(scope)
    except ConfigError as e:
        return {"error": str(e)}
    try:
        with _state.pool.connection() as conn:
            return _get_audit_log(conn, group_id, since)
    except psycopg.OperationalError as e:
        return _operational_error(e)


if __name__ == "__main__":
    startup()
    server.run()
