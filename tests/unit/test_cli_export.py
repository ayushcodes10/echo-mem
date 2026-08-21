from echo_memory.cli.export import (
    _assign_filenames,
    _render_index_markdown,
    _render_node_markdown,
    _slugify,
)


def test_slugify_basic():
    assert _slugify("Postgres") == "postgres"
    assert _slugify("Apache AGE") == "apache-age"
    assert _slugify("t_valid") == "t-valid"


def test_slugify_empty_falls_back_to_node():
    assert _slugify("!!!") == "node"


def test_assign_filenames_no_collision():
    nodes = [{"id": "1", "name": "Postgres"}, {"id": "2", "name": "AGE"}]
    filenames = _assign_filenames(nodes)
    assert filenames == {"1": "postgres.md", "2": "age.md"}


def test_assign_filenames_disambiguates_collisions():
    nodes = [{"id": "1", "name": "Postgres"}, {"id": "2", "name": "Postgres"}]
    filenames = _assign_filenames(nodes)
    assert filenames["1"] == "postgres.md"
    assert filenames["2"] == "postgres-1.md"


def test_render_node_markdown_with_aliases_and_facts():
    node = {"name": "Postgres", "type": "tool", "aliases": ["PG", "postgresql"]}
    edges = [{"relation_type": "uses", "fact": "uses Postgres for storage", "confidence": "extracted"}]
    md = _render_node_markdown(node, edges)
    assert "# Postgres" in md
    assert "**Type:** tool" in md
    assert "**Aliases:** PG, postgresql" in md
    assert "- uses: uses Postgres for storage (extracted)" in md


def test_render_node_markdown_no_facts():
    node = {"name": "Isolated", "type": "topic", "aliases": []}
    md = _render_node_markdown(node, [])
    assert "_(no active facts)_" in md
    assert "**Aliases:**" not in md


def test_render_index_markdown_sorted_and_linked():
    nodes = [{"id": "2", "name": "Zebra"}, {"id": "1", "name": "Apple"}]
    filenames = {"1": "apple.md", "2": "zebra.md"}
    md = _render_index_markdown("g1", nodes, filenames)
    lines = [line for line in md.splitlines() if line.startswith("-")]
    assert lines == ["- [Apple](apple.md)", "- [Zebra](zebra.md)"]
