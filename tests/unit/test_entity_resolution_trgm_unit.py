from echo_memory.ingestion.resolution import _fuzzy_candidates


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self):
        self.queries = []

    def execute(self, query, params):
        self.queries.append((query, params))
        if "node_embedding" in query:
            return _Result([("1", 0.02)])
        if "cypher" in query:
            return _Result([(1, "AWS Organizations SCP p-zlhv81t8")])
        return _Result([("2", "AWS Org SCP p-zlhv81t8", 0.80)])


def test_fuzzy_candidates_fuse_vector_and_trigram_ranks():
    conn = _Connection()
    candidates = _fuzzy_candidates(conn, "group", [1.0], "AWS Org SCP p-zlhv81t8")

    assert [candidate.node_id for candidate in candidates] == ["2", "1"]
    assert candidates[0].similarity == 0.80
    lexical_query = next(query for query, _ in conn.queries if 'FROM echo_memory."Node"' in query)
    # psycopg treats a lone percent as the start of a placeholder; the SQL
    # operator must therefore be doubled in the query string.
    assert " %% %s" in lexical_query
