"""Structured server-side logging: one JSON object per line to stdout, no
raw fact/entity text (see log_write_episode's summary-only fields), so logs
are safe to ship off-box without also shipping user memory content."""

import json
import logging
import sys
import time


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("echo_memory")
    root.setLevel(level)
    root.handlers = [handler]
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"echo_memory.{name}")


def log_write_episode(
    logger: logging.Logger,
    group_id: str,
    session_id: str,
    n_entities: int,
    n_facts: int,
    n_edges_created: int,
    n_ambiguous: int,
    duration_ms: float,
    error: str | None = None,
) -> None:
    """Counts and timing only, never the actual entity/fact text: that's
    user memory content, not operational telemetry."""
    logger.info(
        "write_episode",
        extra={
            "fields": {
                "group_id": group_id,
                "session_id": session_id,
                "n_entities": n_entities,
                "n_facts": n_facts,
                "n_edges_created": n_edges_created,
                "n_ambiguous": n_ambiguous,
                "duration_ms": round(duration_ms, 1),
                "error": error,
            }
        },
    )
