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
