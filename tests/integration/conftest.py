"""Shared fixtures for tests that need a real Postgres+AGE+pgvector database.
Skips automatically if ECHO_MEMORY_DATABASE_URL isn't set or unreachable
(e.g. a fresh clone before docker compose up); CI builds and starts the
database itself, see .github/workflows/ci.yml. Run locally with
`docker compose up -d` first."""

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
DATABASE_URL = os.environ.get("ECHO_MEMORY_DATABASE_URL")


def _reachable(url: str | None) -> bool:
    if not url:
        return False
    try:
        psycopg.connect(url, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


def pytest_collection_modifyitems(items):
    if _reachable(DATABASE_URL):
        return
    n = sum(1 for item in items if "tests/integration" in str(item.fspath))
    # Skipping locally is right - a fresh clone has no database. Skipping in CI
    # is a fully green run with zero coverage of write_episode, retrieval,
    # entity resolution and the whole gate. ECHO_MEMORY_REQUIRE_DB=1 turns the
    # skip into a hard failure, and CI sets it.
    if os.environ.get("ECHO_MEMORY_REQUIRE_DB") == "1":
        raise pytest.UsageError(
            f"ECHO_MEMORY_REQUIRE_DB=1 but the database is unreachable: {n} "
            f"integration tests would have been skipped silently. "
            f"ECHO_MEMORY_DATABASE_URL={DATABASE_URL!r}"
        )
    skip = pytest.mark.skip(reason="ECHO_MEMORY_DATABASE_URL not set or unreachable")
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(skip)


def pytest_terminal_summary(terminalreporter):
    """Say it out loud. A quiet skip reads exactly like a pass."""
    if not _reachable(DATABASE_URL):
        terminalreporter.write_line(
            "SKIPPED all integration tests: database unreachable "
            f"({DATABASE_URL or 'ECHO_MEMORY_DATABASE_URL unset'})",
            yellow=True,
        )


@pytest.fixture
def migrated_db():
    env = {**os.environ, "ECHO_MEMORY_DATABASE_URL": DATABASE_URL}
    alembic = [sys.executable, "-m", "alembic"]
    subprocess.run([*alembic, "upgrade", "head"], cwd=REPO_ROOT, env=env, check=True)
    yield DATABASE_URL
    subprocess.run([*alembic, "downgrade", "base"], cwd=REPO_ROOT, env=env, check=True)
