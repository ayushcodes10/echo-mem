"""The benchmark harness must not quietly drop the turns it finds awkward.

`write_episode` refuses a fact over MAX_STRING_LEN by RETURNING
`{"error": ...}`, not by raising. A harness that ignores the return value
counts the refusal as a write, and the turns it loses are the long ones, which
in LongMemEval are disproportionately the ones carrying an answer. That is a
benchmark measuring a corpus nobody has, in the flattering direction.

So the long turns are split instead, and these pin the two properties that
makes safe: no piece is over the limit, and no text is lost.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from echo_memory.ingestion.write_episode import MAX_STRING_LEN

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "longmemeval-bench.py"


def _harness():
    spec = importlib.util.spec_from_file_location("longmemeval_bench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_short_text_is_left_alone():
    assert _harness().chunks("a single short turn") == ["a single short turn"]


def test_no_piece_can_be_refused_by_write_episode():
    """The prefix ("the assistant said on <date>: ") is added after chunking,
    so the budget has to leave room for it."""
    harness = _harness()
    pieces = harness.chunks("word " * 4_000)

    assert len(pieces) > 1
    assert all(len(p) <= harness.MAX_FACT for p in pieces)
    assert harness.MAX_FACT < MAX_STRING_LEN


def test_nothing_is_lost_in_the_split():
    harness = _harness()
    text = "\n\n".join(f"Paragraph {i}. " + "filler " * 200 for i in range(12))

    rejoined = " ".join(harness.chunks(text)).split()

    assert rejoined == text.split()


def test_it_prefers_a_paragraph_or_sentence_boundary():
    """A chunk that stops mid word is still retrievable and still unreadable.
    Cutting at a boundary costs nothing when one is nearby."""
    harness = _harness()
    text = ("First part. " * 200) + "\n\n" + ("Second part. " * 200)

    first = harness.chunks(text)[0]

    assert first.endswith(".")


def test_a_boundary_too_far_back_is_ignored():
    """Falling back to a hard cut matters: one 4,000 character line with a full
    stop at character 3 must not produce a 3 character chunk and loop."""
    harness = _harness()
    text = "ab. " + "x" * 8_000

    pieces = harness.chunks(text)

    assert all(len(p) <= harness.MAX_FACT for p in pieces)
    assert len(pieces) == 3
