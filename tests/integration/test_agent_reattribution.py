"""Recovering the author of a fact, only where the store can evidence one.

Thirty facts in the author's own store carry no agent_id. They were written by
a long-lived MCP server that had imported the package before agent_id shipped
and kept doing so for eleven days, and migration 0011 turned what it could find
into 'unknown' rather than into 'claude-code' - deliberately, because a fact
claiming an author it cannot support is worse than one admitting it has none.

That refusal was right and it was also total, which left the store permanently
unable to evidence anything about authorship. There is one case where it does
not have to be a guess: a session is one tool's conversation, so a session with
some attributed facts and some unattributed ones has already said who wrote the
rest. Three of the thirty are recoverable that way and twenty-seven are not, and
the difference is what these tests pin.
"""

from __future__ import annotations

import json

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.cli.reattribute import (
    ReattributionError,
    agent_evidence,
    reattribute_agent,
)
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"
OTHER_GROUP = "user:someone-else:shared"


def _embedder(*facts):
    return VectorEmbedder({name: REFERENCE for name in (*facts, "Thing", "Other Thing", "Third Thing")})


def _write(conn, group, session, fact, agent, name="Thing"):
    write_episode(
        conn, group, session,
        [{"name": name, "type": "thing"}],
        [{"source": name, "target": name, "relation_type": "is",
          "fact": fact, "confidence": "extracted"}],
        {name: {"resolved_to": "new"}},
        _embedder(fact), agent_id=agent,
    )


def _strip_author(conn, fact):
    """What the stale server did: no agent_id property at all. AGE drops a
    property whose value is null at CREATE, so this is absence, not null."""
    conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->() WHERE e.fact = $fact
            REMOVE e.agent_id RETURN id(e)
        $$, %s) AS (i agtype)""",
        (json.dumps({"fact": fact}),),
    ).fetchall()


def _author_of(conn, fact):
    row = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->() WHERE e.fact = $fact RETURN e.agent_id
        $$, %s) AS (a agtype)""",
        (json.dumps({"fact": fact}),),
    ).fetchone()
    return str(row[0]).strip('"') if row and row[0] is not None else None


def test_a_session_that_evidences_its_author_is_recoverable(migrated_db):
    """The real case: 19 attributed facts and 3 unattributed ones in one
    session. The session has already said who wrote them."""
    with connect(migrated_db) as conn:
        _write(conn, GROUP, "s-mixed", "the attributed one", "claude-code")
        _write(conn, GROUP, "s-mixed", "the stale one", "claude-code", name="Other Thing")
        _strip_author(conn, "the stale one")

        evidence = agent_evidence(conn, GROUP)
        assert len(evidence) == 1
        assert evidence[0]["missing"] == 1
        assert evidence[0]["recoverable_as"] == "claude-code"

        assert reattribute_agent(conn, GROUP, "s-mixed") == 1
        assert _author_of(conn, "the stale one") == "claude-code"


def test_a_session_with_no_attributed_fact_stays_unattributed(migrated_db):
    """Twenty-seven of the thirty are this. Nothing in the store says who wrote
    them, so nothing here may say either."""
    with connect(migrated_db) as conn:
        _write(conn, GROUP, "s-dark", "nobody knows who wrote this", "claude-code")
        _strip_author(conn, "nobody knows who wrote this")

        evidence = agent_evidence(conn, GROUP)
        assert evidence[0]["recoverable_as"] is None

        with pytest.raises(ReattributionError) as e:
            reattribute_agent(conn, GROUP, "s-dark")

        assert "nothing in the store that can recover them" in str(e.value)
        assert _author_of(conn, "nobody knows who wrote this") is None


def test_a_session_claimed_by_two_tools_is_refused(migrated_db):
    """One session, two agent ids, means the session id is shared and nothing
    can say which tool wrote the unattributed fact. Picking the more frequent
    one would be a guess wearing a majority vote."""
    with connect(migrated_db) as conn:
        _write(conn, GROUP, "s-shared", "written by one", "claude-code")
        _write(conn, GROUP, "s-shared", "written by another", "codex", name="Other Thing")
        _write(conn, GROUP, "s-shared", "written by nobody", "cursor", name="Third Thing")
        _strip_author(conn, "written by nobody")

        assert agent_evidence(conn, GROUP)[0]["recoverable_as"] is None
        with pytest.raises(ReattributionError) as e:
            reattribute_agent(conn, GROUP, "s-shared")

    assert "claude-code" in str(e.value) and "codex" in str(e.value)


def test_recovery_does_not_reach_across_scopes(migrated_db):
    """Same session id in two groups is not the same session. Reading one
    group's authorship to fix another's is the cross-tenant read this project
    has already closed once."""
    with connect(migrated_db) as conn:
        _write(conn, OTHER_GROUP, "s-same-id", "someone else's attributed fact", "codex")
        _write(conn, GROUP, "s-same-id", "our unattributed fact", "claude-code")
        _strip_author(conn, "our unattributed fact")

        assert agent_evidence(conn, GROUP)[0]["recoverable_as"] is None
        with pytest.raises(ReattributionError):
            reattribute_agent(conn, GROUP, "s-same-id")

        assert _author_of(conn, "our unattributed fact") is None


def test_a_fully_attributed_store_has_nothing_to_recover(migrated_db):
    with connect(migrated_db) as conn:
        _write(conn, GROUP, "s-clean", "everything is fine", "claude-code")
        assert agent_evidence(conn, GROUP) == []
