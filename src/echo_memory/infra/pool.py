"""Connection pooling for the MCP server (wired together in PR5). Every
pooled connection needs the same per-connection setup as a standalone one
(see db.connect): AGE loaded, ag_catalog on the search_path, pgvector
registered. psycopg_pool's `configure` hook runs that once per connection,
not once per checkout, so it's cheap even under load."""

from psycopg_pool import ConnectionPool

from echo_memory.infra.db import configure_connection


def make_pool(database_url: str, min_size: int = 0, max_size: int = 3) -> ConnectionPool:
    """A pool that does not require the database to exist yet.

    min_size was 1, so constructing the pool opened a connection immediately -
    inside the MCP handshake. Claude Desktop launches at login, before Docker
    Desktop is up, so the database is unreachable at exactly that moment and the
    handshake stalls: `Couldn't start for Cowork and Code sessions. Error:
    Request timed out` appeared three times in its logs. Nothing is gained by
    connecting before a tool is called; the first call opens one just as well,
    and by then the user has been working for minutes.

    max_size was 10, sized for nothing in particular. This is a single-user
    stdio server and there is one server process per client session, so ten
    connections each against Postgres's default max_connections of 100 is a way
    to exhaust the server once several clients are wired - which is what `adopt`
    is for. Three is ample for one process."""
    return ConnectionPool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        open=True,
        # psycopg_pool waits 30s by default. With min_size=0 that cost moved
        # from startup to the first tool call, which is the right place for it,
        # but 30 seconds of silence before "database unavailable" is its own
        # failure: the agent has already given up, and the user has no idea
        # whether the tool is slow or broken. Five is long enough for a local
        # Postgres that is merely busy and short enough to read as an answer.
        timeout=5,
        configure=configure_connection,
        kwargs={"autocommit": True},
    )
