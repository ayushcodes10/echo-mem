"""The model loads before someone's first question, not inside it.

LocalEmbedder is lazy on purpose - importing it must never download a model, or
a CLI that only prints a queue would pull ninety megabytes. That is right for
the import and wrong for a long-lived server, which knows it will need the
model and has an idle moment at startup to pay for it.

Measured on this machine: constructing LocalEmbedder costs nothing, the first
embed() costs 7.1 seconds, the second 6 milliseconds. Claude Desktop's own
server log shows the same shape in production - query_memory at 6099ms and
5994ms against other calls at 5ms. This is the same lazy-constructor bug Codex
found in the hosted image's Dockerfile, in the local server.
"""

from __future__ import annotations

import threading
import time

from echo_memory import server
from echo_memory.infra.config import Config


class _Embedder:
    dimension = 384

    def __init__(self, fail=False, delay=0.0):
        self.warmed = threading.Event()
        self._fail, self._delay = fail, delay

    def warm(self):
        time.sleep(self._delay)
        if self._fail:
            raise RuntimeError("no model here")
        self.warmed.set()

    def embed(self, text):
        return [1.0] + [0.0] * 383


class _Unwarmable:
    """An embedder from before warm() existed, or a test stub. Must not be a
    problem: the server asks and moves on."""

    dimension = 384

    def embed(self, text):
        return [1.0] + [0.0] * 383


def _config():
    return Config(
        user_id="ayush", agent_id="claude-desktop",
        database_url="postgresql://nobody@localhost/none", project="echo-mem",
    )


def test_the_model_is_loaded_without_being_asked():
    embedder = _Embedder()
    server.startup(config=_config(), embedder=embedder)

    assert embedder.warmed.wait(timeout=5), "nothing warmed the model"


def test_startup_does_not_wait_for_it():
    """The client's handshake is held open by startup, and seven seconds of it
    is how a server gets killed by a connect timeout. Measured at 0.4ms against
    a warm-up that really takes six seconds."""
    embedder = _Embedder(delay=2.0)

    started = time.perf_counter()
    server.startup(config=_config(), embedder=embedder)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"startup blocked for {elapsed:.2f}s"


def test_a_failed_warm_up_does_not_take_the_server_with_it():
    """A model that cannot preload will fail again on the first real call,
    where the caller can be told. A traceback from a background thread would
    only corrupt an MCP server's stderr, which is its log channel."""
    server.startup(config=_config(), embedder=_Embedder(fail=True))

    time.sleep(0.2)
    assert server._state.embedder.embed("still works") is not None


def test_an_embedder_with_no_warm_is_fine():
    server.startup(config=_config(), embedder=_Unwarmable())

    assert server._state.embedder.embed("fine") is not None
