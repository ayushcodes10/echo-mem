"""Applies the real migration against a real database and checks the schema
it produces, including the search_path bug caught during PR1's own manual
testing (plain tables silently landing in ag_catalog instead of public).

See conftest.py for the migrated_db fixture and the DB-reachability skip.
"""

from echo_memory.infra.db import GRAPH_NAME, connect


def test_plain_tables_land_in_public_schema(migrated_db):
    conn = connect(migrated_db)
    rows = conn.execute(
        "SELECT schemaname, tablename FROM pg_tables "
        "WHERE tablename IN ('audit_entry', 'fact_embedding', 'node_embedding')"
    ).fetchall()
    assert {(schema, table) for schema, table in rows} == {
        ("public", "audit_entry"),
        ("public", "fact_embedding"),
        ("public", "node_embedding"),
    }


def test_graph_labels_created(migrated_db):
    conn = connect(migrated_db)
    rows = conn.execute(
        "SELECT name, kind FROM ag_label WHERE graph = "
        "(SELECT graphid FROM ag_graph WHERE name = %s) AND name IN ('Node', 'FACT')",
        (GRAPH_NAME,),
    ).fetchall()
    assert dict(rows) == {"Node": "v", "FACT": "e"}


def test_node_edge_audit_embedding_round_trip(migrated_db):
    conn = connect(migrated_db)

    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH_NAME}', $$
            CREATE (a:Node {{name: 'Postgres', type: 'tool',
                              group_id: 'g1', aliases: []}})
            CREATE (b:Node {{name: 'AGE decision', type: 'decision',
                              group_id: 'g1', aliases: []}})
            CREATE (b)-[e:FACT {{relation_type: 'uses', fact: 'uses Postgres',
                                  confidence: 'extracted', t_valid: 1755600000,
                                  t_invalid: null, group_id: 'g1'}}]->(a)
            RETURN e
        $$) AS (e agtype)"""
    )
    (edge_row,) = conn.execute(
        f"SELECT id FROM {GRAPH_NAME}.\"FACT\" WHERE properties ->> '\"fact\"'::agtype = 'uses Postgres'"
    ).fetchall()
    edge_id = edge_row[0]

    conn.execute(
        "INSERT INTO public.audit_entry "
        "(mutation_type, affected_edge_ids, session_id, summary, group_id) "
        "VALUES ('created', ARRAY[%s]::graphid[], 'sess-1', 'created a fact', 'g1')",
        (edge_id,),
    )
    conn.execute(
        "INSERT INTO public.fact_embedding (edge_id, group_id, embedding) "
        "VALUES (%s, 'g1', (SELECT array_agg(0.0)::vector(384) FROM generate_series(1, 384)))",
        (edge_id,),
    )

    (audit_count,) = conn.execute(
        "SELECT count(*) FROM public.audit_entry WHERE %s = ANY(affected_edge_ids)",
        (edge_id,),
    ).fetchone()
    assert audit_count == 1

    (embedding_count,) = conn.execute(
        "SELECT count(*) FROM public.fact_embedding WHERE edge_id = %s", (edge_id,)
    ).fetchone()
    assert embedding_count == 1
