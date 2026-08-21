from echo_memory.cli.graph import render_graph


def test_render_graph_empty_shows_no_memories_message():
    output = render_graph("solo", "g1", {"nodes": [], "facts": []})
    assert "0 nodes, 0 active facts" in output
    assert "no memories recorded yet" in output


def test_render_graph_shows_fact_edges():
    graph = {
        "nodes": [{"id": "1", "name": "Decision", "type": "topic"}, {"id": "2", "name": "Postgres", "type": "tool"}],
        "facts": [
            {
                "source_id": "1", "source_name": "Decision", "target_id": "2", "target_name": "Postgres",
                "relation_type": "uses", "fact": "decided to use Postgres", "confidence": "extracted",
                "t_valid": 1750000000,
            }
        ],
    }
    output = render_graph("solo", "g1", graph)
    assert "Decision --[uses]--> Postgres" in output
    assert '"decided to use Postgres"' in output
    assert "extracted" in output


def test_render_graph_lists_nodes_with_no_active_facts():
    graph = {
        "nodes": [{"id": "1", "name": "Orphan", "type": "topic"}],
        "facts": [],
    }
    output = render_graph("solo", "g1", graph)
    assert "Nodes with no active facts:" in output
    assert "- Orphan (topic)" in output
