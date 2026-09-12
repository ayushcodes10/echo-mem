"""A tool that can drain the queue must be able to close it.

Marking a document ingested was CLI-only, so the capture loop could only be
finished from a shell. On 2026-09-12 Codex read a pending note, wrote its facts
correctly, and reported: "Its pending marker couldn't be cleared because the
local echo-memory command wasn't available." It was right, and the file stayed
queued for a tool that happened to have a shell.

The listing half has the same shape. Claude Code learns about the queue from a
SessionStart hook; Codex and Claude Desktop run no hooks at all, so nothing
ever told them a queue existed.
"""

from __future__ import annotations

import pytest
from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory import server
from echo_memory.infra.config import Config
from echo_memory.infra.db import connect
from echo_memory.ingestion import capture

PROJECT = "eigen"
PATH = "/Users/ayush/.claude/projects/eigen/memory/eigon-dashboard-api-proxy.md"
OTHER = "/Users/ayush/.claude/projects/eigen/memory/eigon-alb.md"


@pytest.fixture()
def started(migrated_db):
    config = Config(
        user_id="ayush", agent_id="codex", database_url=migrated_db, project=PROJECT
    )
    server.startup(config=config, embedder=VectorEmbedder({"x": REFERENCE}))
    with connect(migrated_db) as conn:
        capture.notice(conn, PATH, PROJECT, "d1")
        capture.notice(conn, OTHER, PROJECT, "d2")
    return migrated_db


def test_a_tool_with_no_shell_can_see_the_queue(started):
    result = server.pending_documents()

    assert result["n"] == 2
    assert {d["path"] for d in result["documents"]} == {PATH, OTHER}
    assert result["project"] == PROJECT


def test_a_tool_with_no_shell_can_close_the_queue(started):
    """The exact failure Codex reported, end to end."""
    assert server.mark_ingested([PATH]) == {"marked": 1, "not_queued": []}

    remaining = server.pending_documents()
    assert remaining["n"] == 1
    assert remaining["documents"][0]["path"] == OTHER


def test_a_path_that_is_not_queued_is_reported_not_swallowed(started):
    """A mistyped path that returns success leaves a document queued forever
    while the caller believes it is done."""
    result = server.mark_ingested(["/tmp/never-noticed.md", PATH])

    assert result["marked"] == 1
    assert result["not_queued"] == ["/tmp/never-noticed.md"]


def test_closing_nothing_is_not_an_error(started):
    assert server.mark_ingested([]) == {"marked": 0, "not_queued": []}
    assert server.pending_documents()["n"] == 2


def test_the_queue_can_be_read_for_another_project(started):
    """Claude Desktop has no working directory, so its own project resolves to
    'unknown' and its default queue is empty. Naming a project is how it
    reaches a real one."""
    assert server.pending_documents(project="no-such-project")["n"] == 0
    assert server.pending_documents(project=PROJECT)["n"] == 2
