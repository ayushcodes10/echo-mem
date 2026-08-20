"""Connection helper: every AGE-aware connection needs the extension loaded
and ag_catalog on the search_path before any Cypher call (see PR0a's spike
notes in the design doc's Foundational spike section)."""

import psycopg

GRAPH_NAME = "echo_memory"


def connect(database_url: str) -> psycopg.Connection:
    conn = psycopg.connect(database_url, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("LOAD 'age'")
        cur.execute('SET search_path = ag_catalog, "$user", public')
    return conn
