"""The sweep against a real database, where its two risks live.

One: it writes. Scratch scopes that survive the measurement would show up in
`status`, `health` and every later `eval` as facts somebody wrote, and the
store would quietly gain a few thousand of them every time this ran.

Two: it must measure rather than extrapolate. A sweep that read the corpus once
and divided would produce a perfectly smooth curve and prove nothing, so the
test that matters is that retrieval actually ran against each size.
"""

from __future__ import annotations

import hashlib
import math

from echo_memory.eval.sweep import drop_scope, materialise, measure, read_corpus
from echo_memory.infra.db import connect
from echo_memory.ingestion.write_episode import write_episode

GROUP = "user:ayush:shared"


class _HashEmbedder:
    """The shared fake raises on unregistered text, by design, and a sweep
    embeds thousands of generated facts and queries. This one is deterministic
    and says nothing about ranking quality, which is right: what is under test
    here is that each size was really built and really queried, not how well
    retrieval did on synthetic facts."""

    dimension = 384

    def embed(self, text: str) -> list[float]:
        # Every one of the 384 dimensions has to come from the text, not from a
        # position-only pattern. A first attempt repeated a 32-byte digest and
        # XORed in the index, which made the index dominate: distinct entity
        # names came out near-parallel, similarity resolution merged them, and
        # three facts became one. That is exactly the collapse this whole sweep
        # would silently under-report.
        raw: list[float] = []
        block = 0
        while len(raw) < self.dimension:
            digest = hashlib.sha256(f"{block}:{text}".encode()).digest()
            raw.extend(b - 127.5 for b in digest)
            block += 1
        raw = raw[: self.dimension]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]


def _embedder():
    return _HashEmbedder()


def _seed(conn, n: int) -> None:
    embedder = _embedder()
    for i in range(n):
        write_episode(
            conn, GROUP, f"s{i}",
            [{"name": f"service {i}", "type": "thing"},
             {"name": f"datastore {i}", "type": "thing"}],
            [{"source": f"service {i}", "target": f"datastore {i}",
              "relation_type": "uses",
              "fact": f"service {i} reads from datastore {i} over a pooled connection",
              "confidence": "extracted"}],
            {f"service {i}": {"resolved_to": "new"},
             f"datastore {i}": {"resolved_to": "new"}},
            embedder, agent_id="claude-code",
        )


def test_the_corpus_is_read_oldest_first(migrated_db):
    """A prefix is only the store as it was at that size if it is a prefix in
    time. Ordered any other way the sweep samples today's store at N facts,
    which is a different and much less interesting claim."""
    with connect(migrated_db) as conn:
        _seed(conn, 4)
        corpus = read_corpus(conn, GROUP)

    assert [row[0] for row in corpus] == [f"service {i}" for i in range(4)]


def test_a_scratch_scope_leaves_nothing_behind(migrated_db):
    """The one that protects the user's own store."""
    with connect(migrated_db) as conn:
        _seed(conn, 3)
        corpus = read_corpus(conn, GROUP)
        scope = "sweep:test:3"
        materialise(conn, scope, corpus, _embedder())

        assert conn.execute(
            "SELECT count(*) FROM public.fact_embedding WHERE group_id = %s", (scope,)
        ).fetchone()[0] == 3

        drop_scope(conn, scope)

        for table in ("fact_embedding", "node_embedding", "group_state", "audit_entry"):
            left = conn.execute(
                f"SELECT count(*) FROM public.{table} WHERE group_id = %s", (scope,)
            ).fetchone()[0]
            assert left == 0, f"{table} kept {left} row(s) of a scratch scope"

        # and the real scope is untouched
        assert len(read_corpus(conn, GROUP)) == 3


def test_it_measures_each_size_and_cleans_up_after_itself(migrated_db):
    """End to end: two points, each with its own inject cost, and no scratch
    scope surviving the call."""
    with connect(migrated_db) as conn:
        _seed(conn, 50)
        points = measure(conn, GROUP, _embedder(), steps=2)

        assert len(points) == 2
        small, large = points
        assert small.facts < large.facts
        # Measured, not divided: the inject cost has to track the fact count.
        assert large.inject_tokens > small.inject_tokens
        assert small.cases > 0 and large.cases > 0

        leftover = conn.execute(
            "SELECT count(*) FROM public.fact_embedding WHERE group_id LIKE 'sweep:%'"
        ).fetchone()[0]
        assert leftover == 0


def test_a_rebuilt_prefix_does_not_lose_facts_to_ambiguity(migrated_db):
    """The regression that made a 680 fact scope come back as 336.

    Two entity names that already coexist in the source scope can score between
    the low and high resolution thresholds when rewritten. Resolution reports
    that as ambiguous and write_episode DEFERS every fact touching it, returning
    normally. A sweep that let that happen would report a smaller corpus with a
    flattering saving and nothing would look wrong.
    """
    from fake_embedder import REFERENCE, VectorEmbedder, unit_vector_at_angle

    # 0.8 sits between LOW_THRESHOLD and HIGH_THRESHOLD: ambiguous, the worst
    # case, neither resolved nor cleanly separate.
    close = unit_vector_at_angle(0.8)
    far = unit_vector_at_angle(0.1)
    embedder = VectorEmbedder({
        "Tim": REFERENCE, "John": close,
        "the standup": far, "the retro": far,
        "Tim runs the standup": far, "John runs the retro": far,
        "Tim the standup. Tim runs the standup": far,
        "John the retro. John runs the retro": far,
    })

    corpus = [
        ("Tim", "the standup", "runs", "Tim runs the standup"),
        ("John", "the retro", "runs", "John runs the retro"),
    ]
    scope = "sweep:ambiguity:2"
    with connect(migrated_db) as conn:
        materialise(conn, scope, corpus, embedder)
        written = conn.execute(
            "SELECT count(*) FROM public.fact_embedding WHERE group_id = %s", (scope,)
        ).fetchone()[0]
        drop_scope(conn, scope)

    assert written == 2, "a fact was deferred for ambiguity and silently lost"
