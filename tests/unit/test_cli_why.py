from echo_memory.cli.why import render_entry, render_history


def test_render_entry_includes_timestamp_and_summary():
    entry = {"timestamp": "2026-08-21T00:00:00+00:00", "summary": "created: uses Postgres"}
    assert render_entry(entry) == "2026-08-21T00:00:00+00:00: created: uses Postgres"


def test_render_history_empty():
    assert render_history("123", []) == "No audit history found for fact '123'."


def test_render_history_multiple_entries_in_order():
    entries = [
        {"timestamp": "t1", "summary": "created: fact A"},
        {"timestamp": "t2", "summary": "invalidated 'fact A', superseded by 'fact B'"},
    ]
    result = render_history("123", entries)
    assert "History for fact 123:" in result
    lines = result.splitlines()
    assert lines[1] == "  t1: created: fact A"
    assert lines[2] == "  t2: invalidated 'fact A', superseded by 'fact B'"
