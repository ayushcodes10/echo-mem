"""The cost and latency baseline, v1a success criterion 5.

Nothing here asserts on a timing. A wall-clock threshold in CI fails on a
loaded runner and teaches people to ignore red builds; the deterministic facts
are that a measurement was produced and that the write path makes no LLM
calls. Timings are output for a human to read, not a gate."""

from fake_embedder import REFERENCE, VectorEmbedder

from echo_memory.cli import benchmark
from echo_memory.cli.main import main
from echo_memory.infra.db import connect

GROUP = "benchmark:test"


def _embedder():
    texts = {"benchmark-subject": REFERENCE, "benchmark-target": REFERENCE}
    for i in range(-1, 10):
        texts[f"benchmark round {i} wrote this fact to measure a real cycle"] = REFERENCE
        texts[f"benchmark round {i}"] = REFERENCE
    return VectorEmbedder(texts)


def test_it_produces_a_measurement_for_every_operation(migrated_db):
    result = benchmark.run(connect(migrated_db), GROUP, _embedder(), rounds=2)

    for key in ("write_episode_ms", "query_memory_ms", "digest_ms"):
        assert set(result[key]) == {"min", "median", "max"}
        assert result[key]["min"] <= result[key]["median"] <= result[key]["max"]


def test_the_write_path_makes_no_llm_calls(migrated_db):
    """The one number here that is not an estimate, and the reason the
    benchmark is worth having: extraction happens in the calling agent."""
    result = benchmark.run(connect(migrated_db), GROUP, _embedder(), rounds=2)

    assert result["llm_calls_per_episode"] == 0
    assert result["llm_calls_per_query"] == 0
    assert result["inference_cost_usd"] == 0.0


def test_cold_start_is_reported_separately_from_steady_state(migrated_db):
    """Averaging the first write into the rest would hide a real per-session
    cost inside a max column while overstating steady-state cost."""
    result = benchmark.run(connect(migrated_db), GROUP, _embedder(), rounds=2)

    assert "cold_start_ms" in result
    assert result["cold_start_ms"] > 0
    assert "cold_start_ms" not in result["write_episode_ms"]


def test_rounds_are_respected(migrated_db):
    result = benchmark.run(connect(migrated_db), GROUP, _embedder(), rounds=3)

    assert result["rounds"] == 3


def test_each_round_writes_a_new_fact_rather_than_superseding(migrated_db):
    """Identical facts supersede rather than create, and supersession is a
    different code path with different cost. The benchmark must measure the
    common case."""
    conn = connect(migrated_db)

    benchmark.run(conn, GROUP, _embedder(), rounds=3)

    active = conn.execute(
        """SELECT count(*) FROM public.fact_embedding WHERE group_id = %s""", (GROUP,)
    ).fetchone()[0]
    assert active == 4, "one cold-start write plus three rounds"


def test_render_names_the_zero_cost_and_the_cold_start(migrated_db):
    result = benchmark.run(connect(migrated_db), GROUP, _embedder(), rounds=2)

    out = benchmark.render(result)

    assert "inference cost          $0.00" in out
    assert "cold start" in out
    assert "Zero by construction" in out
    assert "once per session" in out


def test_cli_runs_a_benchmark(migrated_db, monkeypatch, capsys):
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", "bench")
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", "bench")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", migrated_db)
    monkeypatch.setattr(
        "echo_memory.ingestion.embeddings.LocalEmbedder", lambda: _embedder()
    )

    assert main(["benchmark", "--rounds", "2", "--group", GROUP]) == 0

    assert "cost and latency baseline" in capsys.readouterr().out


def test_cli_rejects_zero_rounds(migrated_db, monkeypatch, capsys):
    monkeypatch.setenv("ECHO_MEMORY_USER_ID", "bench")
    monkeypatch.setenv("ECHO_MEMORY_AGENT_ID", "bench")
    monkeypatch.setenv("ECHO_MEMORY_DATABASE_URL", migrated_db)

    assert main(["benchmark", "--rounds", "0"]) == 1

    assert "at least 1" in capsys.readouterr().err
