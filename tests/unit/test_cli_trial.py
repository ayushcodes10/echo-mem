"""Rendering-only tests for `echo-memory trial`: the criterion 6 block, the
review list, and the observation log. The database side is covered in
tests/integration/test_trial.py."""

from datetime import UTC, date, datetime

from echo_memory.cli.trial import render_check, render_criterion_six, render_log, render_start


def _report(**overrides):
    report = {
        "trial": {
            "started_on": date(2026, 8, 21), "cap_days": 21,
            "day": 3, "days_left": 18, "expired": False,
        },
        "counts": {
            "cross_tool_saves": 0, "same_tool_saves": 0, "duplicates": 0,
            "bad_merges": 0, "dismissed_pairs": 0, "merges_ok": 0,
        },
        "open": {"solo": _empty_scope(), "shared": _empty_scope()},
        "n_open_pairs": 0,
        "n_unreviewed": 0,
        "met": {"saves": False, "duplicates": True, "bad_merges": True},
    }
    return {**report, **overrides}


def _empty_scope():
    return {"duplicate_candidates": [], "unreviewed_resolutions": []}


def test_unstarted_trial_says_the_clock_isnt_running():
    out = "\n".join(render_criterion_six(_report(trial=None)))
    assert "trial clock not started" in out


def test_running_trial_shows_the_day_against_the_cap():
    out = "\n".join(render_criterion_six(_report()))
    assert "day 3 of 21 (started 2026-08-21, 18 left)" in out


def test_expired_trial_says_the_cap_is_hard():
    expired = {"started_on": date(2026, 8, 1), "cap_days": 21, "day": 23, "days_left": 0,
               "expired": True}
    out = "\n".join(render_criterion_six(_report(trial=expired)))
    assert "hard cap" in out
    assert "don't extend" in out


def test_saves_bar_counts_only_cross_tool_ones():
    counts = {"cross_tool_saves": 3, "same_tool_saves": 2, "duplicates": 0,
              "bad_merges": 0, "dismissed_pairs": 0, "merges_ok": 0}
    met = {"saves": True, "duplicates": True, "bad_merges": True}
    out = "\n".join(render_criterion_six(_report(counts=counts, met=met)))
    assert "[x] 3/3 recall saves to a different tool" in out
    assert "+2 same-tool, which the criterion doesn't count" in out


def test_a_bad_merge_fails_its_bar():
    counts = {"cross_tool_saves": 0, "same_tool_saves": 0, "duplicates": 0,
              "bad_merges": 1, "dismissed_pairs": 0, "merges_ok": 0}
    met = {"saves": False, "duplicates": True, "bad_merges": False}
    out = "\n".join(render_criterion_six(_report(counts=counts, met=met)))
    assert "[ ] 1 confirmed bad merges (must be 0)" in out


def test_open_items_are_flagged_in_the_summary():
    out = "\n".join(render_criterion_six(_report(n_open_pairs=2, n_unreviewed=1)))
    assert "2 similar node pair(s) and 1 entity resolution(s) awaiting review" in out


def test_check_prints_the_command_that_records_each_verdict():
    pair = {"node_ids": ["844424930131969", "844424930131970"],
            "names": ["AGE (tool)", "Apache AGE (tool)"], "similarity": 0.497}
    report = _report(
        open={"solo": {"duplicate_candidates": [pair], "unreviewed_resolutions": []},
              "shared": _empty_scope()},
        n_open_pairs=1,
    )
    out = render_check(report)
    assert "AGE (tool)  <->  Apache AGE (tool)   similarity 0.497" in out
    assert "echo-memory --scope solo trial dup 844424930131969 844424930131970" in out
    assert "echo-memory --scope solo trial not-dup 844424930131969 844424930131970" in out


def test_check_lists_resolutions_with_both_verdict_commands():
    resolution = {
        "audit_entry_id": 7, "timestamp": datetime(2026, 8, 22, 9, 30, tzinfo=UTC),
        "node_id": "844424930131969", "node_name": "Postgres (tool)",
        "resolution_detail": "fuzzy match, similarity=0.931", "summary": "resolved",
        "session_id": "sess-1",
    }
    report = _report(
        open={"solo": _empty_scope(),
              "shared": {"duplicate_candidates": [], "unreviewed_resolutions": [resolution]}},
        n_unreviewed=1,
    )
    out = render_check(report)
    assert "#7  Postgres (tool)  (2026-08-22 09:30 UTC)" in out
    assert "fuzzy match, similarity=0.931  [session sess-1]" in out
    assert "echo-memory --scope shared trial merge-ok 7" in out
    assert "echo-memory --scope shared trial bad-merge 7" in out


def test_check_with_nothing_open_still_nudges_about_recall_saves():
    out = render_check(_report())
    assert "Nothing awaiting review." in out
    assert "echo-memory trial save" in out


def test_start_is_idempotent_in_what_it_says():
    fresh = render_start({"started_on": date(2026, 8, 21), "cap_days": 21,
                          "already_started": False})
    again = render_start({"started_on": date(2026, 8, 21), "cap_days": 21,
                          "already_started": True})
    assert fresh == "Trial started on 2026-08-21, 21-day cap."
    assert "already started on 2026-08-21" in again
    assert "Nothing changed" in again


def test_log_renders_a_recall_save_with_both_tools():
    entries = [{
        "id": 1, "timestamp": datetime(2026, 8, 22, 9, 30, tzinfo=UTC),
        "kind": "recall_save", "group_id": "g", "note": "the AGE spike verdict",
        "written_by": "claude-code", "recalled_by": "cursor",
        "node_ids": None, "audit_entry_id": None,
    }]
    out = render_log(entries)
    assert '"the AGE spike verdict"' in out
    assert "written by claude-code -> recalled by cursor" in out


def test_empty_log_says_so():
    assert render_log([]) == "No trial observations recorded yet.\n"
