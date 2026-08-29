"""The criterion 6 measurement fix: recording a recall save from the agent
(T1), suppressing cross-project pair noise (T2), and the guards that keep an
agent-certified gate from drifting (T3).

Context for why these exist: criterion 6 sat at 0/3 for three days not because
recall was broken but because logging a save required a human to notice, switch
to a terminal and type a CLI command. `write_episode` fires dozens of times a
day precisely because an agent can call it inline. See the CEO plan
2026-08-23-close-the-measurement-gap.md."""

import pytest
from fake_embedder import REFERENCE, VectorEmbedder, unit_vector_at_angle

from echo_memory import server
from echo_memory.cli.main import main
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect
from echo_memory.trial import check, observations

NEAR_DUPLICATE = unit_vector_at_angle(0.60)
# Orthogonal to both REFERENCE and NEAR_DUPLICATE, which only vary in the first
# two dimensions, so this node pairs with nothing.
ORTHOGONAL = [0.0, 0.0, 1.0] + [0.0] * 381


def _startup(migrated_db, project="eigen", agent_id="claude-code", vectors=None):
    config = Config(
        user_id="ayush", agent_id=agent_id, database_url=migrated_db, project=project
    )
    server.startup(
        config=config,
        embedder=VectorEmbedder({"anything": REFERENCE, **(vectors or {})}),
    )
    return config


def _fact_written_by(migrated_db, agent_id, fact="a fact worth recalling",
                     then_as="claude-code"):
    """Write one fact as `agent_id` and return its fact_id.

    `record_recall_save` derives written_by from the cited fact's own edge, so
    a test that wants a cross-tool save has to actually put a fact in the store
    under the other tool's name. Until 2026-08-29 the tests passed
    written_by="cursor" into a store with no cursor facts and the gate counted
    it - the bug these helpers exist to make unrepeatable."""
    _startup(migrated_db, agent_id=agent_id,
             vectors={"other": ORTHOGONAL, fact: REFERENCE})
    server.write_episode(
        "shared", f"s-{agent_id}",
        [{"name": "anything", "type": "thing"}, {"name": "other", "type": "thing"}],
        [{"source": "anything", "target": "other", "relation_type": "relates_to",
          "fact": fact, "confidence": "extracted"}],
    )
    result = server.query_memory("shared", None, top_k=10, digest=True)
    fact_id = next(f["fact_id"] for f in result["facts"] if f["fact"] == fact)
    # _startup rebinds the server's global agent id. Restore the recalling
    # tool, or the caller records a same-tool save without noticing.
    _startup(migrated_db, agent_id=then_as)
    return fact_id


# ---------------------------------------------------------------- T1: the tool


def test_agent_records_a_cross_tool_save_that_counts(migrated_db):
    fact_id = _fact_written_by(migrated_db, "cursor")
    _startup(migrated_db, agent_id="claude-code")

    result = server.record_recall_save(
        "shared", fact_id, "the Upstox WS entitlement is account-level"
    )

    assert result["recorded"] is True
    assert result["counts_toward_gate"] is True
    assert result["cross_tool_saves"] == 1
    assert result["required"] == observations.REQUIRED_SAVES


def test_a_save_cannot_be_manufactured_for_a_fact_that_does_not_exist(migrated_db):
    """The gate decides real build work, so its number must be checkable. Until
    2026-08-29 written_by was free text: an agent could type any tool name and
    the save counted, in a store containing nothing that tool ever wrote."""
    _startup(migrated_db, agent_id="claude-code")

    result = server.record_recall_save("shared", "999999", "a save I invented")

    assert "error" in result
    assert "no fact" in result["error"]
    assert result.get("counts_toward_gate") is None


def test_a_fact_from_another_scope_cannot_be_cited(migrated_db):
    """An unscoped lookup would let one tenant's fact evidence another's gate."""
    fact_id = _fact_written_by(migrated_db, "cursor")
    _startup(migrated_db, agent_id="claude-code")

    result = server.record_recall_save("solo", fact_id, "citing across scopes")

    assert "error" in result and "no fact" in result["error"]


def test_recalled_by_defaults_to_this_server(migrated_db):
    config = _startup(migrated_db, agent_id="claude-code")
    server.record_recall_save("shared", _fact_written_by(migrated_db, "cursor"), "something")

    conn = connect(migrated_db)
    entry = observations.list_observations(conn, [config.group_id("shared")])[0]

    assert entry["recalled_by"] == "claude-code"
    assert entry["written_by"] == "cursor"


def test_same_tool_save_is_recorded_but_does_not_count(migrated_db):
    """Recalling your own note from ten minutes ago is not what criterion 6
    measures, but it is still evidence recall works, so it is kept."""
    _startup(migrated_db, agent_id="claude-code")

    result = server.record_recall_save("shared", _fact_written_by(migrated_db, "claude-code"), "my own note")

    assert result["recorded"] is True
    assert result["counts_toward_gate"] is False
    assert result["cross_tool_saves"] == 0
    assert "does not count" in result["note"]


def test_a_missing_fact_id_is_refused(migrated_db):
    """Was test_missing_written_by_is_refused. written_by is no longer a
    parameter - the fact being cited is what the server validates now."""
    _startup(migrated_db)

    result = server.record_recall_save("shared", "", "a save")

    assert "error" in result
    assert "no fact" in result["error"]


def test_a_bad_scope_returns_a_typed_error(migrated_db):
    _startup(migrated_db)

    result = server.record_recall_save("nonsense", "1", "a save")

    assert "error" in result
    assert "scope" in result["error"]


# ------------------------------------------------------- T3: the gate's guards


def test_an_identical_retry_is_a_no_op(migrated_db):
    """An agent retrying after a timeout must not move a counter whose bar is
    exactly three."""
    _startup(migrated_db)

    fid = _fact_written_by(migrated_db, "cursor")
    first = server.record_recall_save("shared", fid, "the same sentence")
    second = server.record_recall_save("shared", fid, "the same sentence")

    assert first["already_recorded"] is False
    assert second["already_recorded"] is True
    assert second["observation_id"] == first["observation_id"]
    assert second["cross_tool_saves"] == 1


def test_two_different_saves_from_one_tool_both_count(migrated_db):
    _startup(migrated_db)

    fid = _fact_written_by(migrated_db, "cursor")
    server.record_recall_save("shared", fid, "the first occasion")
    result = server.record_recall_save("shared", fid, "a different occasion")

    assert result["cross_tool_saves"] == 2


def test_an_oversized_note_is_refused(migrated_db):
    _startup(migrated_db)

    result = server.record_recall_save(
        "shared", _fact_written_by(migrated_db, "cursor"), "x" * (observations.MAX_NOTE_LEN + 1)
    )

    assert "error" in result
    assert "too long" in result["error"]


def test_a_note_at_the_cap_is_accepted(migrated_db):
    _startup(migrated_db)

    result = server.record_recall_save(
        "shared", _fact_written_by(migrated_db, "cursor"), "x" * observations.MAX_NOTE_LEN
    )

    assert result["recorded"] is True


def test_other_observation_kinds_still_raise_on_conflict(migrated_db):
    """Only recall saves are idempotent. A second, contradictory verdict on a
    node pair is a real disagreement and must not silently keep the first."""
    import psycopg

    conn = connect(migrated_db)
    pair = observations.sort_pair(["10", "20"])
    observations.record(conn, "g", observations.NOT_DUPLICATE, "distinct", node_ids=pair)

    with pytest.raises(psycopg.errors.UniqueViolation):
        observations.record(conn, "g", observations.DUPLICATE_NODE, "same", node_ids=pair)


def test_record_reports_whether_it_created_anything(migrated_db):
    conn = connect(migrated_db)

    created = observations.record(
        conn, "g", observations.RECALL_SAVE, "note", written_by="a", recalled_by="b"
    )
    repeated = observations.record(
        conn, "g", observations.RECALL_SAVE, "note", written_by="a", recalled_by="b"
    )

    assert created == {"id": created["id"], "created": True}
    assert repeated == {"id": created["id"], "created": False}


# -------------------------------------------------- T2: cross-project suppression


def _two_projects(migrated_db):
    """A same-project near-duplicate pair inside eigen, and nodes in dugout whose
    projects are genuinely disjoint from eigen's.

    Disjoint matters: a node referenced from both projects legitimately shares a
    project with either side, so it is NOT a cross-project pair. Only nodes whose
    fact sets never overlap are."""
    embedder = VectorEmbedder(
        {
            "AGE": NEAR_DUPLICATE, "Apache AGE": NEAR_DUPLICATE,
            "dugout-be": NEAR_DUPLICATE, "dugout-svc": ORTHOGONAL,
            "the spike passed": REFERENCE, "the deploy branch is master": REFERENCE,
        }
    )
    eigen = Config(user_id="ayush", agent_id="claude-code", database_url=migrated_db,
                   project="eigen")
    server.startup(config=eigen, embedder=embedder)
    server.write_episode(
        "shared", "sess-eigen",
        [{"name": "AGE", "type": "tool"}, {"name": "Apache AGE", "type": "tool"}],
        [{"source": "AGE", "target": "Apache AGE", "relation_type": "same_as",
          "fact": "the spike passed", "confidence": "extracted"}],
    )
    dugout = Config(user_id="ayush", agent_id="claude-code", database_url=migrated_db,
                    project="dugout")
    server.startup(config=dugout, embedder=embedder)
    server.write_episode(
        "shared", "sess-dugout",
        [{"name": "dugout-be", "type": "repo"}, {"name": "dugout-svc", "type": "service"}],
        [{"source": "dugout-be", "target": "dugout-svc", "relation_type": "deploys",
          "fact": "the deploy branch is master", "confidence": "extracted"}],
        {"dugout-be": {"resolved_to": "new"}, "dugout-svc": {"resolved_to": "new"}},
    )
    return eigen


def test_cross_project_pairs_are_suppressed_by_default(migrated_db):
    config = _two_projects(migrated_db)
    conn = connect(migrated_db)

    shown = check.duplicate_candidates(conn, config.group_id("shared"))

    assert shown, "the in-project pair should still surface"
    assert all(c["same_project"] for c in shown)
    assert not any("dugout-be" in " ".join(c["names"]) for c in shown)


def test_all_projects_returns_the_suppressed_ones(migrated_db):
    config = _two_projects(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")

    default = check.duplicate_candidates(conn, group_id)
    everything = check.duplicate_candidates(conn, group_id, all_projects=True)

    assert len(everything) > len(default)
    assert any(not c["same_project"] for c in everything)


def test_same_project_pairs_sort_ahead_of_cross_project(migrated_db):
    config = _two_projects(migrated_db)
    conn = connect(migrated_db)

    everything = check.duplicate_candidates(
        conn, config.group_id("shared"), all_projects=True
    )

    flags = [c["same_project"] for c in everything]
    assert flags == sorted(flags, reverse=True), "same-project pairs must come first"


def test_the_suppressed_count_is_always_reported(migrated_db):
    """F5: a hidden backlog that renders as an empty list is worse than a
    visible one."""
    config = _two_projects(migrated_db)
    conn = connect(migrated_db)

    report = check.build_report(conn, config)

    assert report["n_suppressed_pairs"] >= 1


def test_pairs_carry_the_projects_that_talk_about_them(migrated_db):
    config = _two_projects(migrated_db)
    conn = connect(migrated_db)

    everything = check.duplicate_candidates(
        conn, config.group_id("shared"), all_projects=True
    )

    assert all(c["projects"] for c in everything)
    assert any("dugout" in c["projects"] for c in everything)


def test_cli_check_names_the_hidden_pairs(migrated_db, monkeypatch, capsys):
    config = _two_projects(migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)

    assert main(["--scope", "shared", "trial", "check"]) == 0

    out = capsys.readouterr().out
    assert "span unrelated projects" in out
    assert "--all-projects" in out


def test_cli_all_projects_shows_them_marked(migrated_db, monkeypatch, capsys):
    config = _two_projects(migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)

    assert main(["--scope", "shared", "trial", "check", "--all-projects"]) == 0

    out = capsys.readouterr().out
    assert "[cross-project]" in out


def test_status_names_a_client_that_is_wired_but_has_never_written(migrated_db, tmp_path,
                                                                   monkeypatch):
    """S8-F1's promised line could not render as originally specified:
    `writers()` counts facts, so an agent with none contributes no row and reads
    as absent rather than as zero. The adopt registry supplies the missing half."""
    from echo_memory.cli import adopt, status

    config = _startup(migrated_db, agent_id="claude-code")
    monkeypatch.setattr(
        adopt, "adopted_clients",
        lambda home=None: [{"client": "cursor", "agent_id": "cursor", "path": "x"}],
    )

    scopes = status.fetch_status(connect(migrated_db), config)
    text = status.render_status(scopes, check.build_report(connect(migrated_db), config))

    assert "wired but has never written: cursor" in text


def test_health_reads_a_real_store_end_to_end(migrated_db):
    """collect() touches the graph, the audit log, the trial report and the
    adopt registry. Four sources is four chances for a shape mismatch that no
    unit test on a dict literal would catch."""
    from echo_memory.cli import health

    config = _startup(
        migrated_db, agent_id="claude-code",
        vectors={"other": ORTHOGONAL, "a fact": REFERENCE},
    )
    server.write_episode(
        "shared", "s1",
        [{"name": "anything", "type": "thing"}, {"name": "other", "type": "thing"}],
        [{"source": "anything", "target": "other", "relation_type": "relates_to",
          "fact": "a fact", "confidence": "extracted"}],
    )

    report = health.collect(connect(migrated_db), config)

    assert report["facts"] == 1
    assert report["organic_writes"] == 1
    assert report["imported_writes"] == 0
    assert report["writers"] == {"claude-code": 1}
    assert report["unattributed_facts"] == 0
    assert 0 <= health.score(report) <= 100
    assert "knowledge health" in health.render(report)
