"""Embedding: a local model, no external API call (see the design doc's MCP
tool contract "architecture pivot" note). Swappable behind the Embedder
protocol if local quality proves insufficient later."""

from typing import Protocol


class Embedder(Protocol):
    dimension: int

    def embed(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """all-MiniLM-L6-v2 (384-dim). A placeholder default pending real quality
    tuning (see MATHS.local.md's open questions), not a considered final
    choice. Lazy-loads the model so importing this module never triggers a
    download; only calling embed() does."""

    MODEL_NAME = "all-MiniLM-L6-v2"
    dimension = 384

    def __init__(self):
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.MODEL_NAME)
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._load()
        return model.encode(text, normalize_embeddings=True).tolist()
