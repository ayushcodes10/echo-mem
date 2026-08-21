"""Connection pooling for the MCP server (wired together in PR5). Every
pooled connection needs the same per-connection setup as a standalone one
(see db.connect): AGE loaded, ag_catalog on the search_path, pgvector
registered. psycopg_pool's `configure` hook runs that once per connection,
not once per checkout, so it's cheap even under load."""

from psycopg_pool import ConnectionPool

from echo_memory.infra.db import configure_connection


def make_pool(database_url: str, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    return ConnectionPool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        open=True,
        configure=configure_connection,
        kwargs={"autocommit": True},
    )
