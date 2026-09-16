"""Prompt-time recall: the UserPromptSubmit path.

Every other surface asks the agent to remember to call query_memory. On
2026-08-25 a dugout session received the session-start briefing in context,
then made 31 tool calls without a single memory call. The plumbing was fine;
remembering was the problem. This retrieves against the prompt itself, so
there is no decision to forget."""

import json

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.cli import recall
from echo_memory.cli.main import main
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect
from echo_memory.ingestion import capture

FACT = "chat-module-api.internal resolves to dugout-dev-alb, so it is DEV not prod"


def _seed(migrated_db, extra: dict | None = None):
    """`extra` registers more vectors, for tests that write a second fact. The
    fake refuses text it was not handed, which is the point of it."""
    config = Config(
        user_id="ayush", agent_id="claude-code", database_url=migrated_db, project="dugout"
    )
    server.startup(
        config=config,
        embedder=VectorEmbedder(
            {"chat-module-api": REFERENCE, "genai-web-dug": REFERENCE, FACT: REFERENCE,
             **(extra or {})}
        ),
    )
    server.write_episode(
        "shared", "s1",
        [{"name": "chat-module-api", "type": "hostname"},
         {"name": "genai-web-dug", "type": "repo"}],
        [{"source": "chat-module-api", "target": "genai-web-dug",
          "relation_type": "caused_bug_in", "fact": FACT, "confidence": "extracted"}],
    )
    return config


def test_it_retrieves_without_an_embedder(migrated_db):
    """The hook runs in a fresh process per prompt and the embedding model
    costs 6.2s of cold start. Passing embedder=None must work."""
    config = _seed(migrated_db)

    result = recall.recall_for_prompt(
        connect(migrated_db), config, "is chat-module-api dev or prod"
    )

    assert result["skipped"] is None
    assert any("dugout-dev-alb" in f["fact"] for f in result["facts"])


def test_an_unrelated_prompt_retrieves_nothing(migrated_db):
    config = _seed(migrated_db)

    result = recall.recall_for_prompt(
        connect(migrated_db), config, "what is the weather in reykjavik today"
    )

    assert result["facts"] == []
    assert recall.render_context(result) == "", "silence, not an empty block"


def test_a_short_prompt_is_skipped(migrated_db):
    """'yes', 'go on', 'fix it' match everything lexically and mean nothing."""
    config = _seed(migrated_db)

    result = recall.recall_for_prompt(connect(migrated_db), config, "yes")

    assert result["facts"] == []
    assert "too short" in result["skipped"]


def test_results_are_capped(migrated_db):
    config = _seed(migrated_db)

    result = recall.recall_for_prompt(
        connect(migrated_db), config, "chat-module-api dugout prod dev hostname", top_k=1
    )

    assert len(result["facts"]) <= 1


def test_duplicate_facts_across_scopes_appear_once(migrated_db):
    config = _seed(migrated_db)
    server.write_episode(
        "solo", "s2",
        [{"name": "chat-module-api", "type": "hostname"},
         {"name": "genai-web-dug", "type": "repo"}],
        [{"source": "chat-module-api", "target": "genai-web-dug",
          "relation_type": "caused_bug_in", "fact": FACT, "confidence": "extracted"}],
    )

    result = recall.recall_for_prompt(
        connect(migrated_db), config, "is chat-module-api dev or prod"
    )

    assert [f["fact"] for f in result["facts"]].count(FACT) == 1


def test_rendered_context_tells_the_agent_what_to_do_with_it(migrated_db):
    config = _seed(migrated_db)

    text = recall.render_context(
        recall.recall_for_prompt(connect(migrated_db), config, "is chat-module-api dev")
    )

    assert "instead of re-deriving" in text
    assert "record_recall_save" in text
    assert "keyword match, not a semantic one" in text, "the weaker recall must be disclosed"


def test_hook_output_shape(migrated_db):
    payload = json.loads(recall.render_hook_output("ctx"))

    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert payload["hookSpecificOutput"]["additionalContext"] == "ctx"


def test_cli_stays_silent_in_hook_mode_when_nothing_matches(
    migrated_db, monkeypatch, capsys
):
    """This injects into every prompt the user types; a hook that always speaks
    becomes noise the model learns to skim."""
    config = _seed(migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)

    assert main(["recall", "what is the weather in reykjavik", "--hook-json"]) == 0

    assert capsys.readouterr().out.strip() == ""


def test_cli_emits_hook_json_when_something_matches(migrated_db, monkeypatch, capsys):
    config = _seed(migrated_db)
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", config.user_id)
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", config.agent_id)
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", config.database_url)

    assert main(["recall", "is chat-module-api dev or prod", "--hook-json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "dugout-dev-alb" in payload["hookSpecificOutput"]["additionalContext"]


def test_recalled_facts_carry_the_agent_that_wrote_them(migrated_db):
    """Provenance has to reach the agent for a save to be recordable at all.
    Until 2026-08-28 query_memory returned session_id and source_episode_id
    only, so an agent told to report who wrote a fact found nothing. The tool
    now derives written_by from the cited fact server-side, but agent_id is
    still what makes a recall recognisable as cross-tool in the first place."""
    config = _seed(migrated_db)

    result = recall.recall_for_prompt(
        connect(migrated_db), config, "is chat-module-api dev or prod"
    )

    assert result["facts"], "seeded fact should be retrievable"
    provenance = result["facts"][0]["provenance"]
    assert provenance["agent_id"] == "claude-code"
    assert provenance["project"] == "dugout"
    assert "session_id" in provenance, "existing provenance keys must survive"


def test_injected_facts_carry_their_author_and_fact_id(migrated_db):
    """The hook fires on every prompt and is where a save becomes recognisable.
    It used to emit bare fact text while instructing the agent to call
    record_recall_save - which now requires a fact_id the payload never carried,
    naming an author it never showed."""
    config = _seed(migrated_db)

    text = recall.render_context(
        recall.recall_for_prompt(
            connect(migrated_db), config, "is chat-module-api dev or prod"
        )
    )

    assert "written by claude-code" in text
    assert "fact_id" in text
    assert "record_recall_save with that fact's fact_id" in text


# ------------------------------------------------- the write half of the hook


def test_queued_files_are_surfaced_even_when_nothing_matches(migrated_db):
    """The nudge to drain pending_ingest lived inside query_memory's response,
    so an agent learned work was queued only by calling a tool it does not
    spontaneously call - which is the exact reason this hook exists. Three files
    sat unprocessed for days as a result."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    capture.notice(conn, "/tmp/a-memory-file.md", "dugout", "digest-a")

    result = recall.recall_for_prompt(conn, config, "what is the weather in reykjavik")
    text = recall.render_context(result)

    assert result["facts"] == [], "still no lexical match"
    assert "1 memory file(s) noticed" in text
    assert "echo-memory pending" in text


def test_silence_when_nothing_matches_and_nothing_is_queued(migrated_db):
    """The original contract, now explicit rather than accidental: a hook that
    always speaks becomes noise the model learns to skim."""
    config = _seed(migrated_db)

    result = recall.recall_for_prompt(
        connect(migrated_db), config, "what is the weather in reykjavik"
    )

    assert result["pending"] == 0
    assert recall.render_context(result) == ""


def test_a_store_nobody_is_writing_to_says_so(migrated_db):
    """Reads were made automatic by this hook. Writes stayed a polite request in
    a tool description, and the observed write rate over three days of heavy use
    was zero."""
    _seed(migrated_db)

    text = recall.render_context({
        "facts": [], "pending": 0, "days_since_write": recall.QUIET_DAYS + 4,
    })

    assert "has been written to memory in 7 days" in text
    assert "write_episode now" in text


def test_a_recent_write_is_not_nagged_about(migrated_db):
    assert recall.render_context(
        {"facts": [], "pending": 0, "days_since_write": recall.QUIET_DAYS - 1}
    ) == ""


def test_the_write_half_rides_along_with_matched_facts(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    capture.notice(conn, "/tmp/another.md", "dugout", "digest-b")

    text = recall.render_context(
        recall.recall_for_prompt(conn, config, "is chat-module-api dev or prod")
    )

    assert "dugout-dev-alb" in text, "facts still come first"
    assert "1 memory file(s) noticed" in text


def test_a_short_prompt_still_reports_queued_work(migrated_db):
    """'yes' skips retrieval because it matches everything lexically. Queued
    work has nothing to do with the prompt."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    capture.notice(conn, "/tmp/c.md", "dugout", "digest-c")

    result = recall.recall_for_prompt(conn, config, "yes")

    assert "too short" in result["skipped"]
    assert result["pending"] == 1
    assert "1 memory file(s) noticed" in recall.render_context(result)


NOTIFICATION = """<task-notification>
<task-id>bapxz6bmo</task-id>
<tool-use-id>toolu_01GdSMtojvSvMfkwkL8qb4HM</tool-use-id>
<output-file>/private/tmp/claude-501/-Users-ayush-Desktop-work/tasks/bapxz6bmo.output</output-file>
<status>completed</status>
<summary>Background command "Full suite on a clean database" completed (exit code 0)</summary>
</task-notification>"""


def test_a_machine_notification_is_not_a_prompt(migrated_db):
    """40% of this hook's firings were background-task completions, and on
    those it was worse than useless. prompt_terms takes the first 12 salient
    words; a notification's XML envelope - tag names, a task id, a tool-use id,
    an absolute path - consumes the whole budget before the summary is reached,
    so 99% of them issued nearly the same query and a deterministic ranker
    answered it with the same three facts every time. Those three took 50% of
    everything delivered to notifications, against 10% on typed prompts."""
    config = _seed(migrated_db)

    with server._state.pool.connection() as conn:
        result = recall.recall_for_prompt(conn, config, NOTIFICATION)

    assert result["facts"] == []
    assert result["skipped"] == "nothing here was typed by a person"


def test_a_typed_prompt_survives_the_reminder_stapled_to_it(migrated_db):
    """Stripped rather than detected, because a real question often arrives
    with one of these appended. Skipping on their presence would lose the
    question; skipping on what is left after removing them does not."""
    config = _seed(migrated_db)
    prompt = (
        "is chat-module-api dev or prod\n"
        "<system-reminder>Some long harness note that nobody typed.</system-reminder>"
    )

    with server._state.pool.connection() as conn:
        result = recall.recall_for_prompt(conn, config, prompt)

    assert result["skipped"] is None
    assert any(FACT in f["fact"] for f in result["facts"]), (
        "the real question was lost with the envelope"
    )
    assert "system-reminder" not in result["prompt"]


def test_the_envelope_does_not_eat_the_search_terms(migrated_db):
    """The mechanism, pinned directly: what reaches the ranker is the typed
    words, not the tag names and ids that used to crowd them out."""
    from echo_memory.cli.recall import human_part
    from echo_memory.retrieval.query_memory import MAX_TERMS, prompt_terms

    assert len(prompt_terms(NOTIFICATION)) == MAX_TERMS, (
        "the envelope alone should exhaust the term budget - that is the defect"
    )
    assert prompt_terms(human_part(NOTIFICATION)) == []

    typed = "fix the adaptive floor\n" + NOTIFICATION
    assert prompt_terms(human_part(typed)) == ["fix", "adaptive", "floor"]


def test_a_solo_fact_is_recorded_against_the_solo_scope(migrated_db):
    """The hook queries shared AND solo and recorded everything against shared,
    so every solo fact it delivered was filed under a scope it did not come
    from. The live store showed 227 active solo facts and not one ever returned
    in thirty days - not a fact about retrieval, but the read log pointing at
    the wrong scope.

    It also breaks corroboration: returned_fact_ids is what matches a
    cross-tool recall save to the read that delivered the fact, and a save
    citing a solo fact could never match a read recorded under shared."""
    solo_fact = "chat-module-api also fronts the staging queue worker"
    config = _seed(migrated_db, {"staging queue worker": REFERENCE, solo_fact: REFERENCE})
    server.write_episode(
        "solo", "s-solo",
        [{"name": "chat-module-api", "type": "hostname"},
         {"name": "staging queue worker", "type": "service"}],
        [{"source": "chat-module-api", "target": "staging queue worker",
          "relation_type": "fronts", "fact": solo_fact, "confidence": "extracted"}],
        entity_resolutions={"chat-module-api": {"resolved_to": "new"},
                            "staging queue worker": {"resolved_to": "new"}},
    )

    with server._state.pool.connection() as conn:
        result = recall.recall_for_prompt(
            conn, config, "does chat-module-api front the staging queue worker"
        )
        assert any(solo_fact in f["fact"] for f in result["facts"]), "fixture did not retrieve"
        recall.record_read(conn, config, result, recall.render_context(result), "s-read")

        rows = conn.execute(
            """SELECT group_id, n_facts, returned_fact_ids FROM public.read_event
               WHERE kind = 'hook' ORDER BY id DESC LIMIT 5"""
        ).fetchall()

    by_group = {g: (n, ids) for g, n, ids in rows}
    assert config.group_id("solo") in by_group, (
        f"the solo fact was filed under {list(by_group)}"
    )
    assert by_group[config.group_id("solo")][0] >= 1


def test_the_injected_cost_is_not_counted_twice(migrated_db):
    """Splitting one read into two rows must not double the token total the
    health report adds up."""
    other = "chat-module-api is fronted by the dev load balancer"
    config = _seed(migrated_db, {other: REFERENCE})
    server.write_episode(
        "solo", "s-solo2",
        [{"name": "chat-module-api", "type": "hostname"}],
        [{"source": "chat-module-api", "target": "chat-module-api",
          "relation_type": "is", "fact": other, "confidence": "extracted"}],
        entity_resolutions={"chat-module-api": {"resolved_to": "new"}},
    )

    with server._state.pool.connection() as conn:
        result = recall.recall_for_prompt(conn, config, "is chat-module-api dev or prod")
        context = recall.render_context(result)
        conn.execute("DELETE FROM public.read_event")
        recall.record_read(conn, config, result, context, "s-read2")
        total = conn.execute(
            "SELECT coalesce(sum(injected_chars), 0) FROM public.read_event"
        ).fetchone()[0]

    assert total == len(context), f"{total} charged for a {len(context)}-char injection"


def test_unreturned_counts_facts_retrieval_has_not_reached(migrated_db):
    """The question under every "forgetting layer" is which memories are worth
    keeping, and it is usually answered with a policy - a decay curve, a TTL,
    an eviction rule - chosen before anyone counted. This counts first, and
    proposes nothing: a fact nothing returned may be the one that matters next
    week, or retrieval may simply be failing to reach it."""
    from echo_memory.trial import reads as trial_reads

    config = _seed(migrated_db)
    shared = config.group_id("shared")

    with server._state.pool.connection() as conn:
        before = trial_reads.unreturned(conn, [shared])
        assert before["active"] == 1
        assert before["unreturned"] == 1, "nothing has been read yet"

        result = recall.recall_for_prompt(conn, config, "is chat-module-api dev or prod")
        recall.record_read(conn, config, result, recall.render_context(result), "s-r")
        after = trial_reads.unreturned(conn, [shared])

    assert after["returned"] == 1
    assert after["unreturned"] == 0


def test_unreturned_ignores_superseded_facts(migrated_db):
    """Only active facts. A superseded fact is not unreachable, it is gone, and
    counting it would inflate the share of the store that looks like dead
    weight."""
    from echo_memory.trial import reads as trial_reads

    newer = "chat-module-api resolves to the prod load balancer after all"
    config = _seed(migrated_db, {newer: REFERENCE})
    server.write_episode(
        "shared", "s2",
        [{"name": "chat-module-api", "type": "hostname"},
         {"name": "genai-web-dug", "type": "repo"}],
        [{"source": "chat-module-api", "target": "genai-web-dug",
          "relation_type": "caused_bug_in", "fact": newer, "confidence": "extracted"}],
    )

    with server._state.pool.connection() as conn:
        counts = trial_reads.unreturned(conn, [config.group_id("shared")])

    assert counts["active"] == 1, "the superseded fact was counted as active"
