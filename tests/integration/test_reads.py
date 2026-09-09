"""Read instrumentation.

Writes were counted from the beginning; reads were not counted at all, so
nothing could answer the question the product rests on. The cost is real and
continuous - the prompt hook injects roughly 330 tokens into every prompt
whether or not anything retrieved matters - and criterion 6 cannot see it,
because it counts an agent's self-reported saves rather than what they cost."""

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.cli import recall
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect
from echo_memory.trial import reads

FACT = "chat-module-api.internal resolves to dugout-dev-alb, so it is DEV not prod"


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


def test_a_hook_read_records_what_it_injected(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)

    result = recall.recall_for_prompt(conn, config, "is chat-module-api dev or prod")
    context = recall.render_context(result)
    recall.record_read(conn, config, result, context)

    s = reads.summary(conn, [config.group_id("shared")])
    assert s["reads"] == 1
    assert s["reads_with_facts"] == 1
    assert s["injected_chars"] == len(context)
    assert s["injected_tokens"] == len(context) // reads.CHARS_PER_TOKEN


def test_a_read_that_found_nothing_still_counts(migrated_db):
    """reads-that-found-nothing over reads-total is the ratio that says whether
    retrieval is working. A read only counted when it succeeded would hide it."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)

    result = recall.recall_for_prompt(conn, config, "what is the weather in reykjavik")
    recall.record_read(conn, config, result, recall.render_context(result))

    s = reads.summary(conn, [config.group_id("shared")])
    assert s["reads"] == 1
    assert s["reads_with_facts"] == 0


def test_query_memory_is_counted_too(migrated_db):
    """Both read surfaces, so the ratio covers the tool as well as the hook."""
    config = _seed(migrated_db)

    server.query_memory("shared", None, top_k=5, digest=True)

    s = reads.summary(connect(migrated_db), [config.group_id("shared")])
    assert s["reads"] == 1


def test_recording_never_raises_on_a_broken_connection(migrated_db):
    """This runs on the hot path in a fresh process per prompt. A measurement
    that can fail a prompt is worse than no measurement."""
    conn = connect(migrated_db)
    conn.close()

    reads.record(conn, "g", reads.HOOK, n_facts=1, injected_chars=100)


def test_the_window_excludes_older_reads(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    reads.record(conn, config.group_id("shared"), reads.HOOK, 1, 100)
    conn.execute("UPDATE public.read_event SET at = now() - interval '30 days'")

    assert reads.summary(conn, [config.group_id("shared")], days=7)["reads"] == 0
    assert reads.summary(conn, [config.group_id("shared")], days=60)["reads"] == 1


def test_saves_are_reported_next_to_the_reads_that_produced_them(migrated_db):
    config = _seed(migrated_db)
    conn = connect(migrated_db)
    reads.record(conn, config.group_id("shared"), reads.HOOK, 1, 100)
    result = server.query_memory("shared", None, top_k=5, digest=True)
    server.record_recall_save("shared", result["facts"][0]["fact_id"], "it saved re-explaining")

    s = reads.summary(connect(migrated_db), [config.group_id("shared")])
    assert s["saves"] == 1
    assert s["reads"] >= 1


@pytest.mark.parametrize("kind", [reads.HOOK, reads.QUERY])
def test_both_kinds_land_in_the_same_window(migrated_db, kind):
    conn = connect(migrated_db)
    reads.record(conn, "g", kind, n_facts=1, injected_chars=10)

    assert reads.summary(conn, ["g"])["reads"] == 1


def test_a_read_says_which_project_and_session_it_happened_in(migrated_db):
    """read_event shipped counting reads it could not attribute: group_id is
    the same string for every Claude Code session in every repo, so 12 reads
    across four projects and 12 reads in one looked identical. Asked whether
    the eigen sessions were reading memory, the table had no answer."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)

    result = recall.recall_for_prompt(conn, config, "is chat-module-api dev or prod")
    context = recall.render_context(result)
    recall.record_read(conn, config, result, context, session_id="sess-abc")

    rows = reads.by_project(conn, [config.group_id("shared")])
    assert [(r["project"], r["reads"], r["sessions"]) for r in rows] == [("dugout", 1, 1)]


def test_an_unattributed_read_still_records(migrated_db):
    """The prompt hook may be running against an older CLI mid-upgrade. A read
    without a label is worth more than an exception between user and agent."""
    config = _seed(migrated_db)
    conn = connect(migrated_db)

    reads.record(conn, config.group_id("shared"), reads.HOOK, n_facts=0, injected_chars=0)

    assert reads.summary(conn, [config.group_id("shared")])["reads"] == 1
    assert [r["project"] for r in reads.by_project(conn, [config.group_id("shared")])] == [
        "unattributed"
    ]


def test_a_query_read_records_which_tool_made_it(migrated_db):
    """Reads carried no agent at all until 2026-09-09. With three clients
    connected, "which of them is actually using memory" had no answer: for the
    shared scope every tool's group_id is identical, so a hundred reads and one
    read look the same."""
    from echo_memory import server
    from echo_memory.infra.config import Config
    from echo_memory.trial import reads

    config = Config(
        user_id="ayush", agent_id="cursor", database_url=migrated_db, project="echo-mem"
    )
    server.startup(config=config, embedder=VectorEmbedder({FACT: REFERENCE, "anything": REFERENCE}))
    server.query_memory("shared", query="anything")

    with server._state.pool.connection() as conn:
        row = conn.execute(
            """SELECT agent_id, project FROM public.read_event
               WHERE kind = 'query_memory' ORDER BY at DESC LIMIT 1"""
        ).fetchone()
        summary = reads.summary(conn, [config.shared_group_id()])

    assert row[0] == "cursor", "the read must name the tool that made it"
    assert row[1] == "echo-mem", (
        "project was already a column and query_memory was not writing it, so "
        "the main read surface was the one nobody could account for"
    )
    assert summary["by_agent"].get("cursor") == 1


def test_reads_predating_attribution_are_not_assigned_to_a_likely_tool(migrated_db):
    """Migration 0012 deliberately does not backfill. Guessing claude-code
    because it was likeliest would put a number in the dashboard nobody could
    defend."""
    from echo_memory.infra.config import Config
    from echo_memory.trial import reads

    config = Config(user_id="ayush", agent_id="claude-code", database_url=migrated_db)
    with connect(migrated_db) as conn:
        conn.execute(
            """INSERT INTO public.read_event (group_id, kind, n_facts, injected_chars)
               VALUES (%s, 'query_memory', 1, 10)""",
            (config.shared_group_id(),),
        )
        summary = reads.summary(conn, [config.shared_group_id()])

    assert summary["by_agent"].get(reads.UNATTRIBUTED) == 1
    assert "claude-code" not in summary["by_agent"]
