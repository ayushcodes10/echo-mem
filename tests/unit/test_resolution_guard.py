"""_blocked_from_silent_merge is deterministic, no DB/embedder needed. Values
are the real measurements against the local embedder that motivated the
guard (see resolution.py's module docstring and MATHS.local.md §5)."""

import pytest

from echo_memory.ingestion.resolution import _blocked_from_silent_merge


@pytest.mark.parametrize(
    "a,b",
    [
        ("t_valid", "t_invalid"),
        ("PR-B3", "PR-B2"),
        ("v1a", "v1b"),
        ("valid", "invalid"),
    ],
)
def test_blocks_negation_and_version_pairs(a, b):
    assert _blocked_from_silent_merge(a, b)
    assert _blocked_from_silent_merge(b, a)


@pytest.mark.parametrize(
    "a,b",
    [
        ("Postgres", "PostgreSQL"),
        ("AGE", "Apache AGE"),
        ("pgvector", "pg_vector"),
        ("HNSW index", "HNSW"),
    ],
)
def test_does_not_block_true_duplicates(a, b):
    assert not _blocked_from_silent_merge(a, b)


def test_does_not_block_identical_names():
    assert not _blocked_from_silent_merge("Postgres", "Postgres")
    assert not _blocked_from_silent_merge("Postgres", "postgres")
