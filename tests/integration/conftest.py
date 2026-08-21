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
    skip = pytest.mark.skip(reason="ECHO_MEMORY_DATABASE_URL not set or unreachable")
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture
def migrated_db():
    env = {**os.environ, "ECHO_MEMORY_DATABASE_URL": DATABASE_URL}
    alembic = [sys.executable, "-m", "alembic"]
    subprocess.run([*alembic, "upgrade", "head"], cwd=REPO_ROOT, env=env, check=True)
    yield DATABASE_URL
    subprocess.run([*alembic, "downgrade", "base"], cwd=REPO_ROOT, env=env, check=True)
