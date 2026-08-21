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
        if text not in self._vectors:
            raise KeyError(f"VectorEmbedder has no vector registered for {text!r}")
        return self._vectors[text]


def unit_vector_at_angle(cos_theta: float, dim: int = 384) -> list[float]:
    """A unit vector whose cosine similarity to [1, 0, 0, ...] is exactly
    cos_theta."""
    sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
    return [cos_theta, sin_theta] + [0.0] * (dim - 2)


REFERENCE = [1.0] + [0.0] * 383
