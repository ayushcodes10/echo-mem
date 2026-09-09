"""A deterministic embedder for tests that need exact, controllable cosine
similarity between specific strings (e.g. testing threshold boundaries),
where a real model's semantic quirks would make that unpredictable."""

import math


class VectorEmbedder:
    """Maps known text to hand-picked 384-dim unit vectors. Raises on
    anything not registered, so a test can't silently fall through to
    accidental (and meaningless) real behavior."""

    dimension = 384

    def __init__(self, vectors: dict[str, list[float]]):
        for text, v in vectors.items():
            norm = math.sqrt(sum(x * x for x in v))
            assert abs(norm - 1.0) < 1e-6, f"{text!r}'s vector isn't unit-length (norm={norm})"
            assert len(v) == self.dimension
        self._vectors = vectors

    def embed(self, text: str) -> list[float]:
        if text in self._vectors:
            return self._vectors[text]

        # Facts are embedded as "<source> <target>. <fact>" so the entity names
        # reach the vector (see write_episode.embedding_text). Almost every
        # test here is about resolution, supersession or attribution and
        # registers only the fact text, so fall back to the part after the
        # names rather than making each of them restate the composed string.
        #
        # Still strict: the fallback only fires when the tail is itself
        # registered, so genuinely unknown text raises exactly as before. A
        # test that cares about the composed form registers it and gets it.
        _, separator, tail = text.partition(". ")
        if separator and tail in self._vectors:
            return self._vectors[tail]

        raise KeyError(f"VectorEmbedder has no vector registered for {text!r}")


def unit_vector_at_angle(cos_theta: float, dim: int = 384) -> list[float]:
    """A unit vector whose cosine similarity to [1, 0, 0, ...] is exactly
    cos_theta."""
    sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
    return [cos_theta, sin_theta] + [0.0] * (dim - 2)


REFERENCE = [1.0] + [0.0] * 383
