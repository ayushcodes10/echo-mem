import io
import json
import logging

from echo_memory.infra.logging import JsonFormatter, get_logger, log_write_episode


def _capture_logger():
    logger = get_logger("test")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger, stream


def test_log_write_episode_emits_valid_json_with_counts_not_content():
    logger, stream = _capture_logger()

    log_write_episode(
        logger,
        group_id="g1",
        session_id="s1",
        n_entities=3,
        n_facts=2,
        n_edges_created=2,
        n_ambiguous=1,
        duration_ms=12.345,
    )

    payload = json.loads(stream.getvalue().strip())
    assert payload["message"] == "write_episode"
    assert payload["group_id"] == "g1"
    assert payload["session_id"] == "s1"
    assert payload["n_entities"] == 3
    assert payload["n_facts"] == 2
    assert payload["n_edges_created"] == 2
    assert payload["n_ambiguous"] == 1
    assert payload["duration_ms"] == 12.3
    assert payload["error"] is None

    # never the actual entity/fact text, only counts and identifiers
    assert "fact" not in payload
    assert "entities" not in payload
    assert "text" not in payload


def test_log_write_episode_records_error():
    logger, stream = _capture_logger()

    log_write_episode(
        logger, "g1", "s1", 1, 1, 0, 0, 1.0, error="too many entities: 51 > 50"
    )

    payload = json.loads(stream.getvalue().strip())
    assert payload["error"] == "too many entities: 51 > 50"
