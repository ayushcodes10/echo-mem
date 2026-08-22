import json
import re

from echo_memory.cli.graph_html import render_html


def _embedded_data(html: str) -> dict:
    m = re.search(r"const DATA = (\{.*?\});", html, re.DOTALL)
    return json.loads(m.group(1))


def test_render_html_embeds_scope_and_group_id():
    html = render_html("shared", "user:ayush:shared", {"nodes": [], "facts": []})
    assert "user:ayush:shared" in html
    assert "<code>shared</code>" in html


def test_render_html_embeds_real_data_as_json():
    graph = {
        "nodes": [{"id": "1", "name": "Postgres", "type": "tool"}],
        "facts": [
            {
                "source_id": "1", "source_name": "Postgres", "target_id": "1",
                "target_name": "Postgres", "relation_type": "uses",
                "fact": "decided to use Postgres", "confidence": "extracted",
                "t_valid": 1750000000,
            }
        ],
    }
    html = render_html("solo", "user:ayush:agent:claude-code", graph)
    data = _embedded_data(html)
    assert data == graph


def test_render_html_escapes_script_close_in_fact_text():
    graph = {
        "nodes": [{"id": "1", "name": "A", "type": "t"}, {"id": "2", "name": "B", "type": "t"}],
        "facts": [
            {
                "source_id": "1", "source_name": "A", "target_id": "2", "target_name": "B",
                "relation_type": "uses", "fact": "</script>alert(1)</script>",
                "confidence": "extracted", "t_valid": 1750000000,
            }
        ],
    }
    html = render_html("solo", "g1", graph)
    assert "</script>alert(1)" not in html
    data = _embedded_data(html)
    assert data["facts"][0]["fact"] == "</script>alert(1)</script>"


def test_render_html_handles_empty_graph():
    html = render_html("solo", "user:ayush:agent:claude-code", {"nodes": [], "facts": []})
    assert "No memories recorded yet" in html
