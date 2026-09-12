"""A recall save has to cite a fact the caller was actually given.

Both tool identities on a save are derived from evidence the server holds -
the writer from the cited edge, the reader from the presented key - so the
agent being graded cannot type either. Until 2026-09-13 that was the whole of
the verification: `record_recall_save` took a fact_id and looked it up
directly, so an agent could name a fact it had never queried for and the
criterion would count it.

A reviewer of the paper written from this project made that the sharpest of
seven objections. The read log already recorded every read with its group,
tool and a COUNT of facts returned - the count being the useless half, since
ten facts going out says nothing about whether this one did. Migration 0021
stores which.

What this can and cannot establish is worth stating, because the difference is
the reviewer's actual point. That the fact reached the caller: verifiable, and
now verified. That the recall spared the user a re-explanation: a
counterfactual, not observable from inside the system at any price, and still
the agent's own attestation.
"""

from __future__ import annotations

import json

import pytest
from fake_embedder import REFERENCE, VectorEmbedder, unit_vector_at_angle

from echo_memory import server
from echo_memory.infra.config import Config
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.db import connect
from echo_memory.trial import reads

FACT = "the deploy branch is main, never master"
OTHER = "the cache is invalidated on write"


# Two facts that do not retrieve each other. The first version of this test
# put one fact in the store and queried for something else, so the read
# returned the only fact there was and the "never delivered" case could not
# occur - the test was asserting against a store that could not produce it.
FAR = unit_vector_at_angle(0.05)


def _embedder():
    return VectorEmbedder({
        "Acme": REFERENCE, "release branch": REFERENCE, FACT: REFERENCE,
        "cache": FAR, "write path": FAR, OTHER: FAR,
    })


def _write(config, session="s1"):
    server.write_episode(
        "shared", session,
        [{"name": "Acme", "type": "company"},
         {"name": "release branch", "type": "policy"}],
        [{"source": "Acme", "target": "release branch", "relation_type": "deploys_from",
          "fact": FACT, "confidence": "extracted"}],
        {"Acme": {"resolved_to": "new"}, "release branch": {"resolved_to": "new"}},
    )
    server.write_episode(
        "shared", session,
        [{"name": "cache", "type": "component"}, {"name": "write path", "type": "component"}],
        [{"source": "cache", "target": "write path", "relation_type": "affected_by",
          "fact": OTHER, "confidence": "extracted"}],
        {"cache": {"resolved_to": "new"}, "write path": {"resolved_to": "new"}},
    )


@pytest.fixture
def writer(migrated_db):
    """cursor writes the fact, so a save citing it is genuinely cross-tool."""
    config = Config(user_id="ayush", agent_id="cursor", database_url=migrated_db)
    server.startup(config=config, embedder=_embedder())
    _write(config)
    return config


def _as(migrated_db, agent_id):
    config = Config(user_id="ayush", agent_id=agent_id, database_url=migrated_db)
    server.startup(config=config, embedder=_embedder())
    return config


def test_a_fact_the_caller_never_received_is_refused(writer, migrated_db):
    """The abuse case, and the one the old code could not see. claude-code
    reads something - so the scope has a delivery log and the guard is armed -
    then cites a different fact it was never given."""
    _as(migrated_db, "claude-code")
    delivered = server.query_memory("shared", OTHER, 5)
    got = {str(f["fact_id"]) for f in delivered["facts"]}

    fact_id = _fact_id_for(migrated_db, FACT)
    assert fact_id not in got, "precondition: the cited fact must not have been returned"
    refused = server.record_recall_save("shared", fact_id, "claimed without reading it")

    assert "error" in refused, refused
    assert "ever returned" in refused["error"]
    assert fact_id in refused["error"]


def test_a_fact_this_tool_actually_read_is_corroborated(writer, migrated_db):
    """The honest path, and the strongest grade of evidence available: a read
    by this same tool returned this fact before the claim."""
    _as(migrated_db, "claude-code")
    found = server.query_memory("shared", FACT, 5)
    fact_id = str(found["facts"][0]["fact_id"])

    saved = server.record_recall_save(
        "shared", fact_id, "recalled the deploy branch instead of asking again"
    )

    assert saved.get("recorded") is True, saved
    assert saved["delivery"] == reads.DELIVERED_TO_AGENT
    assert saved["written_by"] == "cursor"
    assert saved["recalled_by"] == "claude-code"
    assert saved["counts_toward_gate"] is True


def test_a_read_by_another_tool_is_weaker_evidence_not_a_refusal(writer, migrated_db):
    """Most of this store's reads arrive by a hook that recorded no tool, so a
    check demanding same-tool evidence would refuse almost every honest save.
    The weaker grade is recorded instead, and named, so the trial can tell the
    two apart rather than the server pretending they are the same."""
    _as(migrated_db, "codex")
    found = server.query_memory("shared", FACT, 5)
    fact_id = str(found["facts"][0]["fact_id"])

    _as(migrated_db, "claude-code")
    saved = server.record_recall_save("shared", fact_id, "codex read it, claude-code claims it")

    assert saved.get("recorded") is True, saved
    assert saved["delivery"] == reads.DELIVERED_TO_GROUP


def test_a_store_with_no_delivery_log_refuses_nothing(writer, migrated_db):
    """The guard on the guard. Every read before migration 0021 recorded a
    count and not the ids, so `delivered` answers None for every fact in a
    store that has not read anything since. Refusing on that would reject every
    honest save on every existing install the moment it upgraded - a check
    firing hardest on whoever has used the thing longest is not a check."""
    _as(migrated_db, "claude-code")

    fact_id = _fact_id_for(migrated_db, FACT)
    saved = server.record_recall_save("shared", fact_id, "nothing has been read yet")

    assert saved.get("recorded") is True, saved
    assert saved["delivery"] is None


def _fact_id_for(migrated_db: str, text: str) -> str:
    with connect(migrated_db) as conn:
        row = conn.execute(
            f"""SELECT * FROM cypher('{GRAPH}', $$
                MATCH ()-[e:FACT]->() WHERE e.fact = $f RETURN id(e)
            $$, %s) AS (edge_id agtype)""",
            (json.dumps({"f": text}),),
        ).fetchone()
    assert row, f"fixture wrote no fact matching {text!r}"
    return str(row[0])
