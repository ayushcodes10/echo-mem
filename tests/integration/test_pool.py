"""Every pooled connection needs the same per-connection setup as a
standalone one (AGE loaded, pgvector registered), applied via psycopg_pool's
configure hook rather than once per checkout. See conftest.py for the
migrated_db fixture."""

from echo_memory.infra.pool import make_pool
from echo_memory.ingestion.embeddings import LocalEmbedder
from echo_memory.ingestion.write_episode import write_episode


def test_pooled_connection_runs_write_episode(migrated_db):
    pool = make_pool(migrated_db, min_size=1, max_size=2)
    pool.wait(timeout=10)
    embedder = LocalEmbedder()
    try:
        with pool.connection() as conn:
            result = write_episode(
                conn, "g1", "s1", [{"name": "Postgres", "type": "tool"}], [], {}, embedder
            )
            assert result == {"edges_created": [], "ambiguous_entities": [], "superseded": []}

        with pool.connection() as conn:
            (count,) = conn.execute("SELECT count(*) FROM public.node_embedding").fetchone()
            assert count == 1
    finally:
        pool.close()


def test_pool_checks_out_multiple_connections_concurrently(migrated_db):
    pool = make_pool(migrated_db, min_size=1, max_size=3)
    pool.wait(timeout=10)
    try:
        with pool.connection() as c1, pool.connection() as c2:
            assert c1 is not c2
            (v1,) = c1.execute("SELECT 1").fetchone()
            (v2,) = c2.execute("SELECT 1").fetchone()
            assert (v1, v2) == (1, 1)
    finally:
        pool.close()
