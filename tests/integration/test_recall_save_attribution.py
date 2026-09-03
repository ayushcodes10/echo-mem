"""Neither side of a cross-tool save may be asserted by the caller.

Criterion 6 counts a save only when the fact's author and its reader are
different tools, and the agent supplying the evidence is the agent being
graded. Both halves therefore have to come from somewhere the agent cannot
choose.

The writer half was closed on 2026-08-29: `written_by` used to be free text,
so the number gating v1a was a string typed by the model being measured. It is
now read from the fact's own edge via fact_id.

The reader half stayed open until end-to-end testing on 2026-09-03 passed
recalled_by="codex" from a claude-code server and watched it produce a counted
cross-tool save. The reader is now the server's own configured agent id, which
comes from the config the client launched it with, and is not a parameter."""

import inspect

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.infra.config import Config

FACT = "a fact written by one tool and read by another"


def _serve(migrated_db, agent_id):
    config = Config(
        user_id="ayush", agent_id=agent_id, database_url=migrated_db, project="echo-mem"
    )
    server.startup(config=config, embedder=VectorEmbedder({"probe": REFERENCE, FACT: REFERENCE}))
    return config


def _write(session_id):
    result = server.write_episode(
        "shared", session_id,
        [{"name": "probe", "type": "test"}],
        [{"source": "probe", "target": "probe", "relation_type": "is",
          "fact": FACT, "confidence": "extracted"}],
        entity_resolutions={"probe": {"resolved_to": "new"}},
    )
    return result["edges_created"][0]


def test_the_reader_cannot_be_claimed(migrated_db):
    """The exact call that used to work: one tool asserting it is another."""
    _serve(migrated_db, "claude-code")
    with pytest.raises(TypeError):
        server.record_recall_save("shared", "1", "note", recalled_by="codex")


def test_recalled_by_is_not_part_of_the_tool_contract(migrated_db):
    _serve(migrated_db, "claude-code")
    assert "recalled_by" not in inspect.signature(server.record_recall_save).parameters


def test_one_tool_alone_cannot_produce_a_cross_tool_save(migrated_db):
    _serve(migrated_db, "claude-code")
    fact_id = _write("cc-1")

    saved = server.record_recall_save("shared", str(fact_id), "read my own note back")

    assert saved["recorded"] is True
    assert saved["counts_toward_gate"] is False
    assert saved["cross_tool_saves"] == 0


def test_a_genuine_cross_tool_save_still_counts(migrated_db):
    """Written by one server, read by another, exactly as two clients run."""
    _serve(migrated_db, "codex")
    fact_id = _write("codex-1")

    _serve(migrated_db, "claude-code")
    saved = server.record_recall_save("shared", str(fact_id), "codex knew this already")

    assert saved["counts_toward_gate"] is True
    assert saved["cross_tool_saves"] == 1
    assert saved["written_by"] == "codex"
    assert saved["recalled_by"] == "claude-code"
