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

FACT = "chat-module-api.dugoutlive.com resolves to dugout-dev-alb, so it is DEV not prod"


def _seed(migrated_db):
    config = Config(
        user_id="ayush", agent_id="claude-code", database_url=migrated_db, project="dugout"
    )
    server.startup(
        config=config,
        embedder=VectorEmbedder(
            {"chat-module-api": REFERENCE, "genai-web-dug": REFERENCE, FACT: REFERENCE}
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
