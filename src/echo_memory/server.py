"""python -m echo_memory.server: wires write_episode, query_memory, and
get_audit_log into one MCP server (see the design doc's MCP tool contract).
Runs over stdio by default (mcp.server.mcpserver's MCPServer.run default),
not a network listener at all, let alone one bound beyond localhost; see
the design doc's Constraints ("v1 is single-user, local-only")."""

from mcp.server.mcpserver import MCPServer

from echo_memory.audit.get_audit_log import get_audit_log as _get_audit_log
from echo_memory.infra.config import Config, ConfigError, load_config
from echo_memory.infra.pool import make_pool
from echo_memory.ingestion.embeddings import Embedder, LocalEmbedder
from echo_memory.ingestion.write_episode import write_episode as _write_episode
from echo_memory.retrieval.query_memory import query_memory as _query_memory

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
    the cost of one extra call. entities/facts must already be extracted by
    the calling agent (this server never calls an LLM itself); see the
    design doc's MCP tool contract for the entity_resolutions round-trip
    when a match is ambiguous."""
    try:
        group_id = _state.config.group_id(scope)
    except ConfigError as e:
        return {"error": str(e)}
    with _state.pool.connection() as conn:
        return _write_episode(
            conn, group_id, session_id, entities, facts, entity_resolutions, _state.embedder
        )


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
    explicitly at session start if you want one, it's never automatic."""
    try:
        group_id = _state.config.group_id(scope)
    except ConfigError as e:
        return {"error": str(e)}
    with _state.pool.connection() as conn:
        return _query_memory(conn, group_id, query, top_k, _state.embedder, digest=digest)


@server.tool()
def get_audit_log(scope: str, since: str | None = None) -> dict:
    """Human-readable audit trail: what was written, invalidated, superseded,
    or resolved, and why. since is an ISO8601 timestamp; entries at or after
    it, chronologically ordered."""
    try:
        group_id = _state.config.group_id(scope)
    except ConfigError as e:
        return {"error": str(e)}
    with _state.pool.connection() as conn:
        return _get_audit_log(conn, group_id, since)


if __name__ == "__main__":
    startup()
    server.run()
