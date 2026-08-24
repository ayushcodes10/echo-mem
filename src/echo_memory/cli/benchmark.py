"""echo-memory benchmark: v1a success criterion 5, "a rough cost and latency
baseline for a real ingestion + query cycle".

Rough is the word in the criterion and it is meant literally. This is a local
single-process measurement against whatever is in the store right now, not a
controlled benchmark: numbers move with hardware, cache warmth and graph size.
It exists to answer two questions honestly - is a write or a read
unexpectedly slow, and what does a cycle cost - not to produce a figure
anyone should quote as a spec.

The cost half is the interesting half, and it is the one number here that is
not an estimate. Echo Memory's write path never calls an LLM: the calling
agent arrives with entities and facts already extracted (see the design doc's
MCP tool contract architecture pivot), and the only model this process runs is
a local sentence-transformers embedder. So inference cost per episode is
exactly zero, by construction rather than by optimisation. That is worth
measuring because it is the axis where the closest architectural comparison,
Zep/Graphiti, is documented weakest: every episode there triggers multiple LLM
calls for extraction, entity resolution and invalidation, so write cost scales
with volume.

Timings are reported, never asserted on. A wall-clock threshold in CI is the
textbook flaky test - it fails on a loaded runner and teaches people to ignore
red builds. The test for this module asserts that a measurement was produced
and that inference cost is zero, both of which are deterministic."""

import statistics
import time

from echo_memory.ingestion.write_episode import write_episode
from echo_memory.retrieval.query_memory import query_memory

# Every LLM call this process makes on the write path. The number is zero and
# the point of naming the constant is that a future change which introduces one
# has to come here and change it.
LLM_CALLS_PER_EPISODE = 0
LLM_CALLS_PER_QUERY = 0

DEFAULT_ROUNDS = 5

_ENTITIES = [
    {"name": "benchmark-subject", "type": "probe"},
    {"name": "benchmark-target", "type": "probe"},
]


def _episode(round_index: int) -> list[dict]:
    return [
        {
            "source": "benchmark-subject",
            "target": "benchmark-target",
            "relation_type": "measured_in",
            # Distinct per round: an identical fact would supersede the previous
            # one rather than create, and supersession is a different code path
            # with different cost. Measure the common case.
            "fact": f"benchmark round {round_index} wrote this fact to measure a real cycle",
            "confidence": "extracted",
        }
    ]


def _timed(fn) -> tuple[float, object]:
    start = time.perf_counter()
    result = fn()
    return (time.perf_counter() - start) * 1000, result


def run(conn, group_id: str, embedder, rounds: int = DEFAULT_ROUNDS) -> dict:
    """Measure a real ingest + query cycle. Writes real facts into group_id, so
    callers should hand it a throwaway scope rather than a scope holding
    memory worth keeping."""
    # The first write is measured separately and reported separately. It pays
    # for LocalEmbedder's lazy model load, and averaging that into the rest
    # would hide it in a "max" column while overstating steady-state cost.
    # It is not an outlier to be discarded either: every session gets its own
    # server process, so somebody really does pay it once per session.
    cold_start_ms, _ = _timed(
        lambda: write_episode(
            conn, group_id, "benchmark-cold", _ENTITIES, _episode(-1), None, embedder,
            project="benchmark", agent_id="benchmark",
        )
    )

    write_ms: list[float] = []
    query_ms: list[float] = []
    digest_ms: list[float] = []

    for index in range(rounds):
        elapsed, _ = _timed(
            lambda i=index: write_episode(
                conn, group_id, f"benchmark-{i}", _ENTITIES, _episode(i), None, embedder,
                project="benchmark", agent_id="benchmark",
            )
        )
        write_ms.append(elapsed)

    for index in range(rounds):
        elapsed, _ = _timed(
            lambda i=index: query_memory(
                conn, group_id, f"benchmark round {i}", 10, embedder
            )
        )
        query_ms.append(elapsed)

    for _ in range(rounds):
        elapsed, _ = _timed(
            lambda: query_memory(conn, group_id, None, 10, embedder, digest=True)
        )
        digest_ms.append(elapsed)

    return {
        "rounds": rounds,
        "cold_start_ms": round(cold_start_ms, 1),
        "write_episode_ms": _summary(write_ms),
        "query_memory_ms": _summary(query_ms),
        "digest_ms": _summary(digest_ms),
        "llm_calls_per_episode": LLM_CALLS_PER_EPISODE,
        "llm_calls_per_query": LLM_CALLS_PER_QUERY,
        "inference_cost_usd": 0.0,
        "embedder": type(embedder).__name__,
    }


def _summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "min": round(ordered[0], 1),
        "median": round(statistics.median(ordered), 1),
        "max": round(ordered[-1], 1),
    }


def render(result: dict) -> str:
    lines = [
        (
            f"Echo Memory - cost and latency baseline ({result['rounds']} rounds, "
            f"{result['embedder']})"
        ),
        "",
        f"{'operation':<20}{'min':>10}{'median':>10}{'max':>10}",
    ]
    for label, key in (
        ("write_episode", "write_episode_ms"),
        ("query_memory", "query_memory_ms"),
        ("query digest", "digest_ms"),
    ):
        s = result[key]
        lines.append(
            f"{label:<20}{s['min']:>9.1f}ms{s['median']:>9.1f}ms{s['max']:>9.1f}ms"
        )
    lines += [
        "",
        (
            "cold start (first write in a process, includes model load)  "
            f"{result['cold_start_ms']:.0f}ms"
        ),
        "",
        "Cost:",
        f"  LLM calls per episode   {result['llm_calls_per_episode']}",
        f"  LLM calls per query     {result['llm_calls_per_query']}",
        f"  inference cost          ${result['inference_cost_usd']:.2f}",
        "",
        "Zero by construction, not by optimisation: extraction happens in the calling",
        "agent, and the only model this process runs is a local embedder. Timings are",
        "a rough local measurement and move with hardware, cache warmth and graph size.",
        "",
        "Cold start is per process, and every session starts its own server process,",
        "so it is paid once per session rather than once per machine.",
    ]
    return "\n".join(lines) + "\n"
