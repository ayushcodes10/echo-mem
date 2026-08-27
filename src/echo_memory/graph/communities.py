"""Finding the clusters in a memory graph.

The dashboard used to colour nodes by project, which is metadata rather than
structure: it says where a fact was written, not what it belongs with. Two
facts written in the same repo can be about entirely different things, and one
idea can span projects.

Communities come from the edges instead. Run against the real store, label
propagation separates `Trade-Ush` from `dugout-be` without being told they are
unrelated, and splits eigen into the product and its self-healing loop, which
project labels cannot do because both are "eigen".

Label propagation rather than Louvain, and hand-written rather than networkx:
the algorithm is thirty lines, this graph is hundreds of nodes rather than
millions, and networkx is a v1b dependency (PR-B2, PPR) that the v1a gate has
not cleared. Borrowing it early for a picture would be scope creep with a
plausible excuse.

Deterministic by construction. Label propagation is normally order-dependent,
so nodes are visited in a fixed sorted order with a fixed seed; a graph that
reshuffled its colours on every render would be unreadable."""

import random
from collections import Counter, defaultdict

# Enough passes to converge on graphs this size; the loop exits early when a
# full pass changes nothing, which is the usual case well before this.
MAX_PASSES = 40
SEED = 7

# A node is a hub when it is far better connected than the graph's norm. Hubs
# keep their place in the graph but stop *donating* their label, so they can no
# longer pull two unrelated clusters into one.
#
# Measured on the real store: an `Ayush` node created during a portfolio
# backfill had degree 19 and welded sixteen unrelated projects into a single
# 27-node blob. Dropping hubs from the graph entirely over-corrects (22
# communities became 79, mostly debris, because hubs also hold together things
# that genuinely belong together). Letting them receive a label but not spread
# one keeps the graph intact and un-welds the blob: 27 becomes 15, and the
# largest clusters balance out.
#
# Relative to mean degree rather than a fixed number, so the rule still means
# something on a graph ten times this size. The floor stops a tiny sparse graph
# from calling an ordinary 3-edge node a hub.
HUB_MIN_DEGREE = 8
HUB_DEGREE_FACTOR = 4.0


def _adjacency(edges: list[tuple[str, str]]) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        if source == target:
            continue
        adjacency[source].add(target)
        adjacency[target].add(source)
    return adjacency


def connected_components(node_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Island membership. Two nodes in different components share no path at
    all, which is the strongest statement this graph can make that two
    memories are unrelated."""
    parent = {node: node for node in node_ids}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for source, target in edges:
        if source in parent and target in parent:
            a, b = find(source), find(target)
            if a != b:
                parent[a] = b

    roots = sorted({find(node) for node in node_ids})
    index = {root: i for i, root in enumerate(roots)}
    return {node: index[find(node)] for node in node_ids}


def hubs(degree: dict, node_ids: list[str]) -> set[str]:
    """Nodes connected far above the graph's norm. See HUB_MIN_DEGREE."""
    if not node_ids:
        return set()
    mean = sum(degree.get(n, 0) for n in node_ids) / len(node_ids)
    cut = max(HUB_MIN_DEGREE, HUB_DEGREE_FACTOR * mean)
    return {n for n in node_ids if degree.get(n, 0) >= cut}


def label_propagation(
    node_ids: list[str], edges: list[tuple[str, str]], hub_set: set[str] | None = None
) -> dict[str, str]:
    """Assign each node a community label: iteratively adopt whichever label is
    most common among your neighbours, ties broken deterministically.

    Hubs are skipped as label *sources*. A node with a hub for its only
    neighbour still follows the hub, so nothing is stranded."""
    hub_set = hub_set or set()
    adjacency = _adjacency(edges)
    labels = {node: node for node in node_ids}
    order = sorted(node_ids)
    rng = random.Random(SEED)
    rng.shuffle(order)

    for _ in range(MAX_PASSES):
        changed = 0
        for node in order:
            neighbours = adjacency.get(node)
            if not neighbours:
                continue
            donors = [n for n in neighbours if n in labels and n not in hub_set]
            if not donors:
                # Every neighbour is a hub: follow them rather than be stranded.
                donors = [n for n in neighbours if n in labels]
            counts = Counter(labels[n] for n in donors)
            if not counts:
                continue
            top = max(counts.values())
            # Sorting the tied labels keeps the outcome stable across runs
            # rather than depending on dict iteration order.
            best = min(label for label, n in counts.items() if n == top)
            if labels[node] != best:
                labels[node] = best
                changed += 1
        if not changed:
            break
    return labels


def detect(nodes: dict[str, str], edges: list[tuple[str, str]]) -> dict:
    """Communities for a graph, each named after its most-connected member.

    `nodes` maps node id to display name. Returns the per-node assignment plus
    an ordered summary suitable for a sidebar: the largest cluster first, named
    by its hub, which is how a reader finds the thing they came for."""
    node_ids = list(nodes)
    if not node_ids:
        return {"of_node": {}, "communities": [], "components": {}}

    degree: Counter = Counter()
    for source, target in edges:
        degree[source] += 1
        degree[target] += 1

    hub_set = hubs(degree, node_ids)
    labels = label_propagation(node_ids, edges, hub_set)
    components = connected_components(node_ids, edges)

    members: dict[str, list[str]] = defaultdict(list)
    for node, label in labels.items():
        members[label].append(node)

    communities = []
    for label, group in members.items():
        # The hub names the cluster. Ties break on name so the label is stable.
        hub = min(group, key=lambda n: (-degree[n], nodes[n]))
        communities.append(
            {
                "id": label,
                "name": nodes[hub],
                "hub": hub,
                "size": len(group),
                "component": components[hub],
            }
        )
    communities.sort(key=lambda c: (-c["size"], c["name"]))

    rank = {c["id"]: i for i, c in enumerate(communities)}
    return {
        "hubs": sorted(hub_set),
        "of_node": {node: rank[label] for node, label in labels.items()},
        "communities": [{**c, "index": rank[c["id"]]} for c in communities],
        "components": components,
        "degree": dict(degree),
    }
