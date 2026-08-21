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
        "Persistent memory across sessions and tools. Call write_episode after "
        "decisions, preferences, or context worth remembering later, not every "
        "message. Call query_memory at the start of a session, or whenever "
        "recalling prior context would help, before asking the user to "
        "re-explain something they likely already told a different tool."
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
    """Record something worth remembering later: a decision, a stated
    preference, context that would otherwise have to be re-explained to a
    different tool or a future session. entities/facts must already be
    extracted by the calling agent (this server never calls an LLM itself);
    see the design doc's MCP tool contract for the entity_resolutions
    round-trip when a match is ambiguous."""
    try:
        group_id = _state.config.group_id(scope)
    except ConfigError as e:
        return {"error": str(e)}
    with _state.pool.connection() as conn:
        return _write_episode(
            conn, group_id, session_id, entities, facts, entity_resolutions, _state.embedder
        )


@server.tool()
def query_memory(scope: str, query: str, top_k: int = 10) -> dict:
    """Recall prior facts relevant to query, from this agent's own memory
    (scope="solo") or the pool shared across this user's agents
    (scope="shared"). Call this at session start or whenever recalling
    prior context would save the user from re-explaining something."""
    try:
        group_id = _state.config.group_id(scope)
    except ConfigError as e:
        return {"error": str(e)}
    with _state.pool.connection() as conn:
        return _query_memory(conn, group_id, query, top_k, _state.embedder)


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
