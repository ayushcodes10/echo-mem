"""Community detection over a memory graph.

The dashboard used to colour by project, which is metadata: it says where a
fact was written, not what it belongs with. These clusters come from the edges,
which is why they can split one project into two ideas and keep two projects
apart without being told they're unrelated."""

from echo_memory.graph import communities


def _line(n):
    """A path graph: 0-1-2-...-n."""
    nodes = {str(i): f"node{i}" for i in range(n)}
    edges = [(str(i), str(i + 1)) for i in range(n - 1)]
    return nodes, edges


def test_two_disconnected_groups_are_separate_communities():
    nodes = {"a": "A", "b": "B", "c": "C", "d": "D"}
    edges = [("a", "b"), ("c", "d")]

    result = communities.detect(nodes, edges)

    assert result["of_node"]["a"] == result["of_node"]["b"]
    assert result["of_node"]["c"] == result["of_node"]["d"]
    assert result["of_node"]["a"] != result["of_node"]["c"]


def test_disconnected_groups_are_also_separate_components():
    """Different components share no path at all - the strongest statement the
    graph can make that two memories are unrelated."""
    nodes = {"a": "A", "b": "B", "c": "C"}
    edges = [("a", "b")]

    result = communities.detect(nodes, edges)

    assert result["components"]["a"] == result["components"]["b"]
    assert result["components"]["c"] != result["components"]["a"]


def test_a_community_is_named_after_its_most_connected_member():
    nodes = {"hub": "Eigon", "x": "X", "y": "Y", "z": "Z"}
    edges = [("hub", "x"), ("hub", "y"), ("hub", "z")]

    result = communities.detect(nodes, edges)

    assert result["communities"][0]["name"] == "Eigon"
    assert result["communities"][0]["hub"] == "hub"


def test_communities_are_ordered_largest_first():
    nodes = {**{str(i): f"n{i}" for i in range(5)}, "x": "X", "y": "Y"}
    edges = [("0", "1"), ("1", "2"), ("2", "3"), ("3", "4"), ("x", "y")]

    result = communities.detect(nodes, edges)

    sizes = [c["size"] for c in result["communities"]]
    assert sizes == sorted(sizes, reverse=True)


def test_detection_is_deterministic():
    """A graph that reshuffled its colours on every render would be unreadable,
    and label propagation is order-dependent unless pinned."""
    nodes, edges = _line(24)

    first = communities.detect(nodes, edges)
    second = communities.detect(nodes, edges)

    assert first["of_node"] == second["of_node"]
    assert [c["name"] for c in first["communities"]] == [
        c["name"] for c in second["communities"]
    ]


def test_edge_order_does_not_change_the_outcome():
    nodes, edges = _line(20)

    forward = communities.detect(nodes, edges)
    backward = communities.detect(nodes, list(reversed(edges)))

    assert forward["of_node"] == backward["of_node"]


def test_every_node_gets_an_index_into_the_community_list():
    nodes, edges = _line(12)

    result = communities.detect(nodes, edges)

    valid = {c["index"] for c in result["communities"]}
    assert set(result["of_node"].values()) <= valid
    assert len(result["of_node"]) == len(nodes)


def test_an_isolated_node_is_its_own_community():
    nodes = {"a": "A", "b": "B", "lonely": "Lonely"}
    edges = [("a", "b")]

    result = communities.detect(nodes, edges)

    assert result["of_node"]["lonely"] not in (result["of_node"]["a"],)
    assert any(c["name"] == "Lonely" and c["size"] == 1 for c in result["communities"])


def test_self_loops_do_not_break_detection():
    nodes = {"a": "A", "b": "B"}
    edges = [("a", "a"), ("a", "b")]

    result = communities.detect(nodes, edges)

    assert result["of_node"]["a"] == result["of_node"]["b"]


def test_an_empty_graph_is_handled():
    result = communities.detect({}, [])

    assert result["communities"] == []
    assert result["of_node"] == {}


def test_edges_referencing_unknown_nodes_are_survivable():
    """Facts can outlive a node filter; detection must not raise on a dangling
    endpoint."""
    nodes = {"a": "A", "b": "B"}
    edges = [("a", "b"), ("a", "ghost")]

    result = communities.detect(nodes, edges)

    assert set(result["of_node"]) == {"a", "b"}


def test_a_hub_joining_two_groups_merges_them():
    """The real store had exactly this: an 'Ayush' node linking sixteen
    unrelated projects into one component."""
    nodes = {"hub": "Hub", "a1": "A1", "a2": "A2", "b1": "B1", "b2": "B2"}
    edges = [("a1", "a2"), ("b1", "b2"), ("hub", "a1"), ("hub", "b1")]

    result = communities.detect(nodes, edges)

    assert len(set(result["components"].values())) == 1


def test_a_hub_no_longer_welds_two_groups_together():
    """The real store had exactly this: an 'Ayush' node with degree 19, joined
    to many members of many projects, welding sixteen unrelated ones into a
    single 27-node blob."""
    nodes = {"hub": "Hub"}
    edges = []
    for side in ("a", "b"):
        for i in range(9):
            nodes[f"{side}{i}"] = f"{side.upper()}{i}"
        edges += [(f"{side}{i}", f"{side}{i + 1}") for i in range(8)]
        # A hub is joined to many members of each group, not just one.
        edges += [("hub", f"{side}{i}") for i in range(6)]

    result = communities.detect(nodes, edges)

    assert "hub" in result["hubs"]
    assert result["of_node"]["a8"] != result["of_node"]["b8"], (
        "the far ends of two groups must not share a community through the hub"
    )


def test_a_low_degree_bridge_is_not_treated_as_a_hub():
    """A known limit, stated rather than hidden: the rule is about degree, so a
    node joining two groups by one edge each still merges them. That is a
    bridge, and separating on bridges would need articulation-point detection,
    which is a different algorithm than this one."""
    nodes = {"bridge": "Bridge"}
    edges = []
    for side in ("a", "b"):
        for i in range(6):
            nodes[f"{side}{i}"] = f"{side.upper()}{i}"
        edges += [(f"{side}{i}", f"{side}{i + 1}") for i in range(5)]
        edges.append(("bridge", f"{side}0"))

    result = communities.detect(nodes, edges)

    assert "bridge" not in result["hubs"]
    assert len(set(result["components"].values())) == 1


def test_a_hub_still_gets_a_community_of_its_own(migrated_db=None):
    nodes = {"hub": "Hub", **{f"n{i}": f"N{i}" for i in range(12)}}
    edges = [("hub", f"n{i}") for i in range(12)]

    result = communities.detect(nodes, edges)

    assert "hub" in result["of_node"], "a hub is still placed, never dropped"
    assert result["components"]["hub"] == result["components"]["n0"]


def test_a_node_whose_only_neighbour_is_a_hub_is_not_stranded():
    nodes = {"hub": "Hub", "lonely": "Lonely", **{f"n{i}": f"N{i}" for i in range(12)}}
    edges = [("hub", f"n{i}") for i in range(12)] + [("hub", "lonely")]

    result = communities.detect(nodes, edges)

    assert result["of_node"]["lonely"] is not None


def test_an_ordinary_graph_has_no_hubs():
    """The threshold is relative to mean degree, so a small even graph should
    not have an ordinary node called a hub."""
    nodes = {str(i): f"n{i}" for i in range(10)}
    edges = [(str(i), str(i + 1)) for i in range(9)]

    assert communities.detect(nodes, edges)["hubs"] == []


def test_hub_detection_scales_with_the_graph():
    """A fixed threshold would call every well-connected node in a large graph
    a hub. Degree 9 is a hub among chains, ordinary among stars."""
    degree = {"a": 9, **{str(i): 1 for i in range(40)}}
    sparse = communities.hubs(degree, list(degree))

    dense = communities.hubs({k: 9 for k in degree}, list(degree))

    assert "a" in sparse
    assert dense == set(), "when everything has degree 9, nothing is exceptional"
