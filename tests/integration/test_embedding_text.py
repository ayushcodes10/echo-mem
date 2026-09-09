"""What text gets embedded for a fact, and re-embedding when that changes.

The entity names are structure the store already has and never put into the
vector, while the question an agent asks is entity-shaped. Measured over 219
cases, by query shape:

    query names both entities   MRR 0.604 -> 0.776
    query names one entity      MRR 0.579 -> 0.659
    query names neither         MRR 0.976 -> 0.959

The middle row is the honest one. The first is the eval's own query shape and
therefore its most flattering - the query is literally a substring of the
embedded text. The third is the cost.

A fact written before this change carries a vector of the fact alone. Mixed
conventions do not error; they quietly rank worse than either would alone,
which is why `reindex` exists and why these tests check it is complete and
idempotent rather than merely that it runs.
"""

from __future__ import annotations

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.cli.reindex import facts_needing_embedding, reindex, render
from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import embedding_text, write_episode

GROUP = "user:ayush:shared"
FACT = "deploys only from the release branch, never main"


def test_the_entity_names_are_embedded_with_the_fact():
    assert embedding_text("Acme", "release branch", FACT) == (
        f"Acme release branch. {FACT}"
    )


def test_a_fact_with_no_entity_names_is_embedded_alone():
    """Never produce a leading ". " on a fact whose endpoints are unknown - it
    would embed punctuation as if it were content."""
    assert embedding_text("", "", FACT) == FACT
    assert embedding_text("Acme", "", FACT) == FACT


class _Recording(VectorEmbedder):
    """Captures what it was asked to embed, which is the thing under test."""

    def __init__(self, vectors):
        super().__init__(vectors)
        self.seen: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.seen.append(text)
        return super().embed(text)


def _embedder():
    return _Recording({
        "Acme": REFERENCE, "release branch": REFERENCE, FACT: REFERENCE,
        f"Acme release branch. {FACT}": REFERENCE,
    })


def _write(conn, embedder):
    return write_episode(
        conn, GROUP, "s1",
        [{"name": "Acme", "type": "company"},
         {"name": "release branch", "type": "policy"}],
        [{"source": "Acme", "target": "release branch",
          "relation_type": "deploys_from", "fact": FACT, "confidence": "extracted"}],
        {"Acme": {"resolved_to": "new"}, "release branch": {"resolved_to": "new"}},
        embedder, agent_id="claude-code",
    )


def test_the_write_path_embeds_the_names_too(migrated_db):
    embedder = _embedder()
    with connect(migrated_db) as conn:
        assert _write(conn, embedder).get("edges_created")

    assert f"Acme release branch. {FACT}" in embedder.seen, (
        f"the fact was embedded without its entity names: {embedder.seen}"
    )


def test_reindex_covers_every_active_fact(migrated_db):
    with connect(migrated_db) as conn:
        _write(conn, _embedder())
        assert len(facts_needing_embedding(conn, [GROUP])) == 1

        result = reindex(conn, [GROUP], _embedder())

    assert result == {"facts": 1, "updated": 1}


def test_reindex_is_idempotent(migrated_db):
    """Safe to re-run after an interrupted pass, which is the whole reason it
    updates in place rather than rebuilding."""
    with connect(migrated_db) as conn:
        _write(conn, _embedder())
        first = reindex(conn, [GROUP], _embedder())
        vector_after_first = conn.execute(
            "SELECT embedding FROM public.fact_embedding"
        ).fetchone()[0]

        second = reindex(conn, [GROUP], _embedder())
        vector_after_second = conn.execute(
            "SELECT embedding FROM public.fact_embedding"
        ).fetchone()[0]

    assert first == second
    # pgvector hands back a Vector, which is not iterable; to_list() is the API.
    assert vector_after_first.to_list() == vector_after_second.to_list()


def test_reindex_reports_an_empty_scope_rather_than_claiming_work(migrated_db):
    with connect(migrated_db) as conn:
        assert "nothing to reindex" in render(reindex(conn, [GROUP], _embedder()))
