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


def test_flat_extra_fields_survive():
    """Every call site that reached for Python's documented extra={"k": v}
    idiom was silently dropping its fields, because the formatter only read
    record.fields. Both shapes must work or the next one breaks the same way."""
    logger, stream = _capture_logger()

    logger.info("an_event", extra={"observation_id": 7, "cross_tool": True})

    payload = json.loads(stream.getvalue())
    assert payload["observation_id"] == 7
    assert payload["cross_tool"] is True
    assert payload["message"] == "an_event"


def test_nested_and_flat_fields_can_coexist():
    logger, stream = _capture_logger()

    logger.info("mixed", extra={"flat": 1, "fields": {"nested": 2}})

    payload = json.loads(stream.getvalue())
    assert payload["flat"] == 1
    assert payload["nested"] == 2


def test_standard_record_attributes_are_not_leaked_as_fields():
    logger, stream = _capture_logger()

    logger.info("plain")

    payload = json.loads(stream.getvalue())
    assert set(payload) == {"ts", "level", "logger", "message"}


def test_unserializable_values_do_not_crash_the_log_line():
    logger, stream = _capture_logger()

    logger.info("odd", extra={"path": object()})

    assert json.loads(stream.getvalue())["path"].startswith("<object")


def test_configure_logging_writes_to_stderr_not_stdout():
    """stdout is the MCP protocol channel: a log line there is framed as a
    protocol message and corrupts the stream."""
    import sys

    from echo_memory.infra.logging import configure_logging

    configure_logging()
    handler = logging.getLogger("echo_memory").handlers[0]

    assert handler.stream is sys.stderr
    assert handler.stream is not sys.stdout


def test_server_startup_installs_the_json_formatter(monkeypatch):
    """configure_logging existed but nothing called it, so at runtime there was
    no JSON formatting at all. Startup must install it before anything can log."""
    from echo_memory import server
    from echo_memory.infra.config import Config
    from echo_memory.infra.logging import JsonFormatter

    logging.getLogger("echo_memory").handlers = []
    monkeypatch.setattr(server, "make_pool", lambda _url: None)

    server.startup(config=Config(user_id="u", agent_id="a", database_url="postgresql://x/y"))

    handlers = logging.getLogger("echo_memory").handlers
    assert handlers and isinstance(handlers[0].formatter, JsonFormatter)
