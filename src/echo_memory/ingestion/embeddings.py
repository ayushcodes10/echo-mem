"""Embedding: a local model, no external API call (see the design doc's MCP
tool contract "architecture pivot" note). Swappable behind the Embedder
protocol if local quality proves insufficient later."""

import threading
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
        # Loading takes about seven seconds and can now be asked for from two
        # places at once - a warm-up thread and a real query. Without the lock
        # both build a SentenceTransformer, which is the cost this exists to
        # pay once.
        self._lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                import logging

                from sentence_transformers import SentenceTransformer

                # sentence-transformers logs device/model-load info at INFO by
                # default; an MCP stdio server's stderr is meant for structured
                # JSON logs (see infra/logging.py), not this library's own
                logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
                self._model = SentenceTransformer(self.MODEL_NAME)
        return self._model

    def warm(self) -> None:
        """Load the model now rather than inside someone's first question.

        Measured on this machine: constructing LocalEmbedder costs nothing and
        the first embed() costs 7.1 seconds, the second 6 milliseconds. Claude
        Desktop's own server log shows exactly that shape in production - two
        query_memory calls at 6099ms and 5994ms against others at 5ms.

        Lazy loading is right for the import, which is why it is there: a CLI
        that only prints a queue must not download a model. It is wrong for a
        long-lived server, which knows it will need the model and has an idle
        moment at startup to pay for it.
        """
        self.embed("warm")

    def embed(self, text: str) -> list[float]:
        model = self._load()
        return model.encode(text, normalize_embeddings=True, show_progress_bar=False).tolist()
