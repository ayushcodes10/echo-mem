"""_blocked_from_silent_merge is deterministic, no DB/embedder needed. Values
are the real measurements against the local embedder that motivated the
guard (see resolution.py's module docstring and MATHS.local.md §5)."""

import pytest

from echo_memory.ingestion.resolution import (
    _blocked_from_silent_merge,
    _differing_numeric_tokens,
)


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


# --- numbers anywhere in the name, not only at the end ------------------------
#
# The trial produced 155 confirmed-distinct pairs and 5 confirmed-same ones.
# Exactly one pair of each sits above HIGH_THRESHOLD, which makes them the only
# two data points that bear on the silent-merge decision at all - and the rule
# below is the one that separates them.

@pytest.mark.parametrize(
    "a,b,reason",
    [
        # 0.958 on the real embedder, the highest-scoring confirmed-distinct
        # pair in the whole trial, and above HIGH_THRESHOLD. Two production
        # hosts. _TRAILING_VERSION misses it because the name ends in 'com'.
        ("prod-api.dugoutlive.com", "prod-api-v2.dugoutlive.com", "a version in the middle"),
        ("migration 0007", "migration 0120", "different numbers, same shape"),
        ("PR-B3", "PR-B2", "what the trailing rule already caught"),
        ("v1a", "v1b", "same"),
        ("server", "server 2024", "a number on one side only"),
    ],
)
def test_a_disagreement_about_a_number_blocks_the_silent_merge(a, b, reason):
    assert _differing_numeric_tokens(a, b), reason
    assert _differing_numeric_tokens(b, a), reason


@pytest.mark.parametrize(
    "a,b",
    [
        # 0.927, the only confirmed-same pair above HIGH_THRESHOLD. Both names
        # carry the same identifier and differ by an abbreviation, which is
        # exactly what a silent merge is for.
        ("AWS Org SCP p-zlhv81t8", "AWS Organizations SCP p-zlhv81t8"),
        ("criterion 6", "criterion 6 saves bar"),
        ("Postgres", "PostgreSQL"),
        ("AGE", "Apache AGE"),
    ],
)
def test_agreeing_about_numbers_leaves_the_merge_alone(a, b):
    assert not _differing_numeric_tokens(a, b)
    assert not _differing_numeric_tokens(b, a)
