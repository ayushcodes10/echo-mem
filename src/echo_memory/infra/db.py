"""Connection helper: every AGE-aware connection needs the extension loaded
and ag_catalog on the search_path before any Cypher call (see PR0a's spike
notes in the design doc's Foundational spike section)."""

import psycopg
from pgvector.psycopg import register_vector

GRAPH_NAME = "echo_memory"


def configure_connection(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("LOAD 'age'")
        cur.execute('SET search_path = ag_catalog, "$user", public')
    register_vector(conn)


def connect(database_url: str) -> psycopg.Connection:
    conn = psycopg.connect(database_url, autocommit=True)
    configure_connection(conn)
    return conn
