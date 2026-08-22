from echo_memory.cli.status import render_status


def _scope(group_id, nodes=0, facts=0, calls=0, audit=None):
    return {
        "group_id": group_id,
        "nodes": nodes,
        "active_facts": facts,
        "write_episode_calls": calls,
        "audit_counts": audit or {},
    }


def test_no_data_yet_checks_nothing():
    scopes = {
        "solo": _scope("user:ayush:agent:claude-code"),
        "shared": _scope("user:ayush:shared"),
    }
    out = render_status(scopes)
    assert "[ ] both solo and shared scopes have real data" in out
    assert "[ ] at least one entity_resolved audit entry" in out
    assert "[ ] at least one fact mutation audit entry" in out


def test_both_scopes_with_data_checks_scope_criterion():
    scopes = {
        "solo": _scope("g-solo", nodes=2, facts=1, calls=1, audit={"created": 1}),
        "shared": _scope("g-shared", nodes=3, facts=2, calls=1, audit={"created": 2}),
    }
    out = render_status(scopes)
    assert "[x] both solo and shared scopes have real data" in out
    assert "[x] at least one fact mutation audit entry" in out


def test_only_one_scope_with_data_does_not_check_scope_criterion():
    scopes = {
        "solo": _scope("g-solo", nodes=2, facts=1, calls=1, audit={"created": 1}),
        "shared": _scope("g-shared"),
    }
    out = render_status(scopes)
    assert "[ ] both solo and shared scopes have real data" in out


def test_entity_resolved_in_either_scope_checks_that_criterion():
    scopes = {
        "solo": _scope("g-solo"),
        "shared": _scope("g-shared", nodes=1, audit={"entity_resolved": 1}),
    }
    out = render_status(scopes)
    assert "[x] at least one entity_resolved audit entry" in out


def test_fact_superseded_also_counts_as_a_mutation():
    scopes = {
        "solo": _scope("g-solo", nodes=1, audit={"fact_superseded": 1}),
        "shared": _scope("g-shared"),
    }
    out = render_status(scopes)
    assert "[x] at least one fact mutation audit entry" in out
