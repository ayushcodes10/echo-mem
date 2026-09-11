"""Report the graph's shape by median, not mean.

Mean degree was quoted as 2.11 for weeks. The distribution is heavy-tailed, so
the mean is held up by a handful of hubs while the typical node has one edge.
Measured on the author's store: median degree 1, 64% of nodes with exactly one
edge, 83% with two or fewer, top 5% holding 32% of all degree.

The distinction decides real work. A degree-1 node is a leaf and can never be
traversed THROUGH, so multi-hop retrieval over a graph of leaves dead-ends
immediately. Reporting 61 clusters as "structure is forming" over such a graph
is fragmentation described as a strength.
"""

from __future__ import annotations

from echo_memory.cli import health


def _graph(edges, n_nodes):
    return {
        "nodes": [{"id": str(i), "name": f"n{i}", "type": "t"} for i in range(n_nodes)],
        "facts": [{"source_id": str(a), "target_id": str(b)} for a, b in edges],
    }


def test_a_star_reports_the_leaf_not_the_hub():
    """The exact shape a mean hides: one hub of degree 9, nine leaves. Mean
    degree is 1.8 and sounds connected; the median is 1."""
    star = _graph([(0, i) for i in range(1, 10)], 10)
    c = health._connectivity(star)

    assert c["median_degree"] == 1
    assert c["leaf_share"] == 0.9


def test_a_well_connected_graph_reports_as_such():
    ring = _graph([(i, (i + 1) % 6) for i in range(6)], 6)
    c = health._connectivity(ring)

    assert c["median_degree"] == 2
    assert c["leaf_share"] == 0.0


def test_an_empty_graph_does_not_divide_by_zero():
    assert health._connectivity(_graph([], 0)) == {"median_degree": 0, "leaf_share": 0.0}


def _h(**over):
    base = {
        "nodes": 100, "facts": 100, "organic_writes": 50, "imported_writes": 0,
        "last_write": "2026-09-09", "days_since_write": 0, "writers": {"claude-code": 50},
        "silent_agents": [], "orphans": [], "components": 1, "clusters": 5,
        "unreviewed_pairs": 0, "unattributed_facts": 0, "duplicates": 0,
        "bad_merges": 0, "reads": {}, "median_degree": 4, "leaf_share": 0.1,
    }
    base.update(over)
    return base


def test_clusters_are_a_strength_only_when_the_graph_is_connected():
    strong, _, _ = health.findings(_h(clusters=5, leaf_share=0.1))
    assert any("clusters" in s for s in strong)


def test_clusters_over_a_graph_of_leaves_are_not_called_structure():
    """This read as a strength for weeks over a store whose median node had one
    edge. Many small clusters is fragmentation."""
    strong, attention, rec = health.findings(_h(clusters=61, leaf_share=0.64))

    assert not any("structure is forming" in s for s in strong)
    assert any("one edge or none" in a for a in attention)
    assert any("Reuse existing entities" in r for r in rec)


def test_the_advice_names_what_to_do_rather_than_the_number():
    _, _, rec = health.findings(_h(leaf_share=0.8, median_degree=1))
    assert any("query_memory first" in r for r in rec)
