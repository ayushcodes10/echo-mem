"""Seeing a server that is running code older than the code on disk.

An MCP stdio server holds what it imported at spawn, so upgrading the package
changes nothing until the client restarts. That gap cost this store 30 facts
with no author and 7 with no project, each time with correct code on disk and a
green test suite.

Migration 0017 added audit_entry.writer_version to make it visible, and the
first version of the check skipped every null - reasoning that rows written
before the column existed carry no version and must not be guessed at. True,
and it made the check blind to exactly the servers it was built for: one old
enough to predate the column stamps nothing, forever, so the newest row keeps
saying "nothing recorded" and the check keeps skipping it.

A null is uninformative only before the column existed. After that moment it is
the signal.
"""

from __future__ import annotations

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.cli.health import stale_writer
from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"
FACT = "the deploy branch is master"


def _write(conn, session="s1"):
    write_episode(
        conn, GROUP, session,
        [{"name": "deploy branch", "type": "policy"}],
        [{"source": "deploy branch", "target": "deploy branch", "relation_type": "is",
          "fact": FACT, "confidence": "extracted"}],
        {"deploy branch": {"resolved_to": "new"}},
        VectorEmbedder({"deploy branch": REFERENCE, FACT: REFERENCE}),
        agent_id="claude-code", project="echo-mem",
    )


def _forget_versions(conn):
    """What a server too old to know about the column leaves behind."""
    conn.execute("UPDATE public.audit_entry SET writer_version = NULL")


def test_a_current_writer_is_not_flagged(migrated_db):
    with connect(migrated_db) as conn:
        _write(conn)
        assert stale_writer(conn, [GROUP]) is None


def test_a_writer_that_stamps_an_older_version_is_flagged(migrated_db):
    with connect(migrated_db) as conn:
        _write(conn)
        conn.execute("UPDATE public.audit_entry SET writer_version = '0.0.1'")

        assert stale_writer(conn, [GROUP]) == "0.0.1"


def test_a_writer_that_stamps_nothing_at_all_is_flagged(migrated_db):
    """The case the first version of this check could not see, and the only one
    that has ever actually happened."""
    with connect(migrated_db) as conn:
        _write(conn)
        _forget_versions(conn)

        assert stale_writer(conn, [GROUP]) == "before versions were recorded"


def test_rows_from_before_the_column_existed_are_still_not_guessed_at(migrated_db):
    """The original reasoning holds for genuinely old rows. A store whose last
    write predates the column must not be accused of running a stale server."""
    with connect(migrated_db) as conn:
        _write(conn)
        _forget_versions(conn)
        conn.execute(
            """UPDATE public.schema_moment SET occurred_at = now() + interval '1 day'
                WHERE name = 'writer_version_expected'"""
        )

        assert stale_writer(conn, [GROUP]) is None


def test_an_empty_store_says_nothing(migrated_db):
    with connect(migrated_db) as conn:
        assert stale_writer(conn, [GROUP]) is None


@pytest.mark.parametrize("stale", ["0.0.1", "before versions were recorded"])
def test_the_finding_tells_the_reader_to_restart_the_client(stale):
    """A diagnostic that does not name the next move is a complaint, and this
    one's next move is not guessable: nothing about the symptom suggests that
    the fix is restarting a different application."""
    from echo_memory.cli import health

    _, attention, rec = health.findings({
        "facts": 10, "nodes": 10, "organic_writes": 10, "imported_writes": 0,
        "days_since_write": 0, "writers": {"claude-code": 5, "codex": 5},
        "silent_agents": [], "orphans": [], "components": 1, "clusters": 2,
        "median_degree": 2, "leaf_share": 0.1, "unreviewed_pairs": 0,
        "unattributed_facts": 0, "duplicates": 0, "bad_merges": 0,
        "reads": {}, "stale_writer": stale,
    })

    assert any(stale in a for a in attention)
    assert any("Restart the client" in r for r in rec)
