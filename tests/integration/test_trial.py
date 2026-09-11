"""End-to-end tests for the v1a trial instrumentation against a real
Postgres+AGE+pgvector database: recording observations, the duplicate/merge
scans that decide what a human still has to look at, and criterion 6's
tallies. See conftest.py for the migrated_db fixture and DB-reachability skip."""

import json
from datetime import date

import pytest
from fake_embedder import REFERENCE, VectorEmbedder, unit_vector_at_angle

from echo_memory import server
from echo_memory.cli.main import main
from echo_memory.infra.config import Config
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.db import connect
from echo_memory.trial import check, observations

# Between LOW_THRESHOLD (0.45) and HIGH_THRESHOLD (0.92): close enough to be
# worth a human's look, not close enough to merge silently. Two such names
# arriving in the same episode both create nodes (resolution.py's documented
# in-batch limitation), which is exactly the split criterion 6 counts.
NEAR_DUPLICATE = unit_vector_at_angle(0.60)
# Above HIGH_THRESHOLD: resolves silently into the existing node and writes
# the entity_resolved audit entry that `trial check` asks a human to review.
SAME_ENTITY = unit_vector_at_angle(0.95)


def _seed(migrated_db, scope="shared"):
    """Produces one split pair (AGE / Apache AGE) and one non-exact merge
    (Postgresql into Postgres), the two shapes `trial check` surfaces."""
    config = Config(user_id="ayush", agent_id="claude-code", database_url=migrated_db)
    embedder = VectorEmbedder(
        {
            "AGE": NEAR_DUPLICATE,
            "Apache AGE": NEAR_DUPLICATE,
            "Postgres": REFERENCE,
            "Postgresql": SAME_ENTITY,
            "the spike confirmed AGE traversal is fast enough": REFERENCE,
            "Postgres is the storage substrate": REFERENCE,
            "Postgres holds the graph": REFERENCE,
        }
    )
    server.startup(config=config, embedder=embedder)
    server.write_episode(
        scope, "sess-1",
        [
            {"name": "AGE", "type": "tool"},
            {"name": "Apache AGE", "type": "tool"},
            {"name": "Postgres", "type": "tool"},
        ],
        [
            {"source": "AGE", "target": "Apache AGE", "relation_type": "same_as",
             "fact": "the spike confirmed AGE traversal is fast enough",
             "confidence": "extracted"},
            # Postgres needs a fact of its own: an entity no fact mentions is
            # no longer given a node, so listing it alone would leave the
            # Postgresql merge with nothing to resolve against.
            {"source": "Postgres", "target": "AGE", "relation_type": "hosts",
             "fact": "Postgres holds the graph", "confidence": "extracted"},
        ],
    )
    server.write_episode(
        scope, "sess-2",
        [{"name": "Postgresql", "type": "tool"}, {"name": "AGE", "type": "tool"}],
        [{"source": "Postgresql", "target": "AGE", "relation_type": "hosts",
          "fact": "Postgres is the storage substrate", "confidence": "extracted"}],
    )
    return config


def _env(monkeypatch, config):
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)


def test_trial_clock_starts_once_and_does_not_move(migrated_db):
    conn = connect(migrated_db)

    first = observations.start_trial(conn, date(2026, 8, 21))
    second = observations.start_trial(conn, date(2026, 9, 1))

    assert first["already_started"] is False
    assert second["already_started"] is True
    assert second["started_on"] == date(2026, 8, 21)


def test_only_cross_tool_saves_count_toward_the_bar(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")

    observations.record(conn, group_id, observations.RECALL_SAVE, "the AGE verdict",
                        written_by="claude-code", recalled_by="cursor")
    observations.record(conn, group_id, observations.RECALL_SAVE, "the same thing again",
                        written_by="cursor", recalled_by="cursor")

    counts = observations.counts(conn, [group_id])
    assert counts["cross_tool_saves"] == 1
    assert counts["same_tool_saves"] == 1


def test_a_save_whose_author_was_never_recorded_counts_for_neither(migrated_db):
    """'unknown' is unequal to every real agent id, so counting it as
    cross-tool would satisfy `written_by != recalled_by` because one side is
    missing rather than because two tools were involved."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")

    observations.record(conn, group_id, observations.RECALL_SAVE, "a fact with no author",
                        written_by="unknown", recalled_by="cursor")

    counts = observations.counts(conn, [group_id])
    assert counts["cross_tool_saves"] == 0
    assert counts["same_tool_saves"] == 0
    assert counts["unattributed_saves"] == 1


def test_unattributed_facts_elsewhere_do_not_invalidate_a_real_save(migrated_db):
    """The bar used to require the whole store to be attributed, which refused
    saves naming real tools at both ends over unrelated facts the check itself
    called unrecoverable - a bar nothing could clear. The evidence for a save
    is that save's own two agent ids."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")
    observations.start_trial(conn, date(2026, 8, 21))

    # A fact somewhere else in the store that lost its author, exactly as the
    # stale MCP server left thirty of them.
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT {{group_id: $gid}}]->()
            SET e.agent_id = 'unknown' RETURN id(e) LIMIT 1
        $$, %s) AS (i agtype)""",
        (json.dumps({"gid": group_id}),),
    ).fetchall()

    for i in range(3):
        observations.record(conn, group_id, observations.RECALL_SAVE, f"real save {i}",
                            written_by="claude-code", recalled_by="codex")

    report = check.build_report(conn, config, today=date(2026, 8, 23))
    assert report["unattributed_facts"] >= 1, "the test did not create the condition"
    assert report["met"]["saves"], "three evidenced saves were refused by unrelated facts"


def test_an_identical_name_is_flagged_as_certain_not_ranked_among_guesses(migrated_db):
    """Two nodes with one name in one scope are the same entity by the
    resolver's own rule - _exact_match would return one for a mention of the
    other - so it is not a similarity judgement at all. Everything else in the
    queue sits in [0.477, 0.927] where confirmed-same and confirmed-distinct
    pairs overlap, and mixing the two buries the certainty: a duplicate written
    this morning sat at the top of a hundred coin flips and nobody saw it.

    Built by renaming a second node onto the first's name, which is the state
    the resolver's `resolved_to="new"` path used to produce directly.
    """
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")

    original, twin = (
        str(r[0])
        for r in conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH (n:Node {{group_id: $gid}})
                WHERE n.name IN ['AGE', 'Apache AGE'] RETURN id(n) $$, %s)
                AS (i agtype)""",
            (json.dumps({"gid": group_id}),),
        ).fetchall()
    )
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE id(n) = $nid SET n.name = 'AGE' RETURN id(n)
        $$, %s) AS (i agtype)""",
        (json.dumps({"nid": int(twin)}),),
    ).fetchall()
    # The rename does not move the stored vector, so give it the one two
    # identical names would actually produce.
    conn.execute(
        """UPDATE public.node_embedding SET embedding = (
               SELECT embedding FROM public.node_embedding WHERE node_id::text = %s)
            WHERE node_id::text = %s""",
        (original, twin),
    )

    found = check.duplicate_candidates(conn, group_id)
    certain = [c for c in found if c["certain"]]

    assert len(certain) == 1, f"identical names not flagged: {[c['names'] for c in found]}"
    assert certain[0]["names"] == ["AGE (tool)", "AGE (tool)"]
    # And it leads, rather than sitting wherever cosine happened to put it.
    assert found[0]["certain"] is True


def test_a_pair_judgement_cannot_span_two_scopes(migrated_db):
    """The trial's single recorded duplicate turned out to be 'Ayush' in solo
    and 'Ayush' in shared - correct scoping, not one entity split in two, sat
    in the tallies as the only duplicate this store ever confirmed. The pair
    scanner never crosses a group boundary; an id typed by hand did."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)

    mine = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node {{group_id: $gid}}) RETURN id(n) LIMIT 2
        $$, %s) AS (i agtype)""",
        (json.dumps({"gid": config.group_id("shared")}),),
    ).fetchall()
    assert len(mine) == 2, "the fixture did not produce two nodes in shared"

    # Filing a shared-scope pair under the solo scope: both ids are real nodes
    # the same person owns, and neither belongs to the scope being judged.
    with pytest.raises(observations.TrialError) as e:
        observations.record(
            conn, config.group_id("solo"), observations.DUPLICATE_NODE,
            "same name in two scopes",
            node_ids=[str(mine[0][0]), str(mine[1][0])],
        )
    assert "not in" in str(e.value)

    # The same call with both nodes inside the scope is still fine.
    assert observations.record(
        conn, config.group_id("shared"), observations.NOT_DUPLICATE, "reviewed",
        node_ids=[str(mine[0][0]), str(mine[1][0])],
    )["id"]


def test_an_observation_needs_a_note(migrated_db):
    conn = connect(migrated_db)
    with pytest.raises(observations.TrialError):
        observations.record(conn, "g", observations.RECALL_SAVE, "   ")


def test_a_pair_is_stored_sorted_so_swapped_order_collides(migrated_db):
    assert observations.sort_pair(["20", "10"]) == observations.sort_pair(["10", "20"])
    with pytest.raises(observations.TrialError):
        observations.sort_pair(["10", "10"])


def test_similar_nodes_that_stayed_separate_are_flagged(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)

    candidates = check.duplicate_candidates(conn, config.group_id("shared"))

    pairs = {tuple(sorted(c["names"])) for c in candidates}
    assert ("AGE (tool)", "Apache AGE (tool)") in pairs
    assert all(c["similarity"] >= 0.45 for c in candidates)


def test_a_judged_pair_stops_being_flagged(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")

    before = check.duplicate_candidates(conn, group_id)
    observations.record(
        conn, group_id, observations.NOT_DUPLICATE, "different things",
        node_ids=observations.sort_pair(before[0]["node_ids"]),
    )

    after = check.duplicate_candidates(conn, group_id)
    assert len(after) == len(before) - 1
    assert before[0]["node_ids"] not in [c["node_ids"] for c in after]


def test_exact_match_resolutions_are_excluded_from_review_by_default(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")

    default = check.unreviewed_resolutions(conn, group_id)
    with_exact = check.unreviewed_resolutions(conn, group_id, include_exact=True)

    # sess-2 re-mentions "AGE" by exact name and folds "Postgresql" into
    # "Postgres" by embedding similarity: only the latter needs judging.
    assert [r["resolution_detail"] for r in default] == [
        d for d in [r["resolution_detail"] for r in with_exact] if d != "exact match"
    ]
    assert len(default) == 1
    assert default[0]["resolution_detail"].startswith("fuzzy match")
    assert default[0]["node_name"] == "Postgres (tool)"
    assert len(with_exact) > len(default)


def test_a_reviewed_resolution_stops_being_listed(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")

    pending = check.unreviewed_resolutions(conn, group_id)
    observations.record(
        conn, group_id, observations.MERGE_OK, "same database",
        audit_entry_id=pending[0]["audit_entry_id"],
    )

    assert check.unreviewed_resolutions(conn, group_id) == []


def test_report_fails_the_gate_until_the_bars_are_met(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")
    observations.start_trial(conn, date(2026, 8, 21))

    report = check.build_report(conn, config, today=date(2026, 8, 23))
    assert report["trial"]["day"] == 3
    assert report["trial"]["days_left"] == 18
    assert report["met"] == {"saves": False, "duplicates": True, "bad_merges": True}
    assert report["n_open_pairs"] >= 1
    assert report["n_unreviewed"] == 1

    for i in range(3):
        observations.record(conn, group_id, observations.RECALL_SAVE, f"save {i}",
                            written_by="claude-code", recalled_by="cursor")
    observations.record(conn, group_id, observations.BAD_MERGE, "two different tools merged",
                        audit_entry_id=check.unreviewed_resolutions(conn, group_id)[0]
                        ["audit_entry_id"])

    report = check.build_report(conn, config, today=date(2026, 8, 23))
    assert report["met"] == {"saves": True, "duplicates": True, "bad_merges": False}


def test_expired_trial_is_reported_as_expired(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    observations.start_trial(conn, date(2026, 8, 1))

    report = check.build_report(conn, config, today=date(2026, 8, 30))
    assert report["trial"]["expired"] is True
    assert report["trial"]["days_left"] == 0


def test_cli_records_a_save_and_shows_it_in_the_log(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db)
    _env(monkeypatch, config)

    assert main(["--scope", "shared", "trial", "save", "the AGE verdict",
                 "--from", "cursor"]) == 0
    assert main(["--scope", "shared", "trial", "log"]) == 0

    out = capsys.readouterr().out
    assert "Recorded recall save #" in out
    assert "written by cursor -> recalled by claude-code" in out


def test_cli_warns_when_a_save_is_same_tool(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db)
    _env(monkeypatch, config)

    assert main(["trial", "save", "recalled my own note", "--from", "claude-code"]) == 0

    assert "doesn't count toward criterion 6's cross-tool bar" in capsys.readouterr().out


def test_cli_refuses_a_second_verdict_on_the_same_resolution(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db)
    _env(monkeypatch, config)
    conn = connect(migrated_db)
    audit_entry_id = check.unreviewed_resolutions(conn, config.group_id("shared"))[0][
        "audit_entry_id"
    ]

    assert main(["--scope", "shared", "trial", "merge-ok", str(audit_entry_id)]) == 0
    assert main(["--scope", "shared", "trial", "bad-merge", str(audit_entry_id), "no"]) == 1

    assert "already has a recorded verdict" in capsys.readouterr().err


def test_cli_rejects_an_unknown_audit_entry(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db)
    _env(monkeypatch, config)

    assert main(["--scope", "shared", "trial", "merge-ok", "999999"]) == 1

    assert "no audit entry #999999" in capsys.readouterr().err


def test_cli_check_lists_open_items_with_their_commands(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db)
    _env(monkeypatch, config)

    assert main(["--scope", "shared", "trial", "check"]) == 0

    out = capsys.readouterr().out
    assert "trial clock not started" in out
    assert "one entity split in two?" in out
    assert "echo-memory --scope shared trial dup " in out
    assert "echo-memory --scope shared trial merge-ok " in out


def test_status_reports_criterion_six(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db)
    _env(monkeypatch, config)
    observations.start_trial(connect(migrated_db), date(2026, 8, 21))

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "Criterion 6, the v1a -> v1b exit criteria" in out
    assert "[ ] 0/3 recall saves to a different tool" in out
    assert "awaiting review - run `echo-memory trial check`" in out


def test_a_retracted_observation_stays_in_the_record_and_stops_counting(migrated_db):
    """The trial's only recorded duplicate was two nodes in two scopes -
    correct scoping, judged in good faith on ids nothing validated at the time.
    Deleting the row edits the record of a trial; leaving it leaves the exit
    gate reading a wrong tally. Retraction is the third option."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    group_id = config.group_id("shared")
    pair = [
        str(r[0])
        for r in conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH (n:Node {{group_id: $gid}}) RETURN id(n) LIMIT 2 $$, %s)
                AS (i agtype)""",
            (json.dumps({"gid": group_id}),),
        ).fetchall()
    ]
    assert len(pair) == 2

    recorded = observations.record(
        conn, group_id, observations.DUPLICATE_NODE, "judged in error",
        node_ids=observations.sort_pair(pair),
    )
    assert observations.counts(conn, [group_id])["duplicates"] == 1

    observations.retract(conn, recorded["id"], "the two nodes are in different scopes")

    counts = observations.counts(conn, [group_id])
    assert counts["duplicates"] == 0
    assert counts["retracted"] == 1

    # The row and the reason are still there.
    row = conn.execute(
        """SELECT note, retracted_reason FROM public.trial_observation WHERE id = %s""",
        (recorded["id"],),
    ).fetchone()
    assert row[0] == "judged in error"
    assert "different scopes" in row[1]


def test_a_retraction_needs_a_reason(migrated_db):
    """A retraction with no reason is a deletion wearing a different name."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    recorded = observations.record(
        conn, config.group_id("shared"), observations.RECALL_SAVE, "a save",
        written_by="codex", recalled_by="claude-code",
    )

    with pytest.raises(observations.TrialError):
        observations.retract(conn, recorded["id"], "   ")

    assert observations.counts(conn, [config.group_id("shared")])["cross_tool_saves"] == 1


def test_an_observation_is_not_retracted_twice(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    recorded = observations.record(
        conn, config.group_id("shared"), observations.RECALL_SAVE, "a save",
        written_by="codex", recalled_by="claude-code",
    )
    observations.retract(conn, recorded["id"], "recorded against the wrong tool")

    with pytest.raises(observations.TrialError) as e:
        observations.retract(conn, recorded["id"], "again")
    assert "already retracted" in str(e.value)


def test_retracting_something_that_does_not_exist_says_so(migrated_db):
    conn = connect(migrated_db)
    with pytest.raises(observations.TrialError) as e:
        observations.retract(conn, 999999, "a reason")
    assert "no observation" in str(e.value)
