#!/usr/bin/env python3
"""Run LongMemEval against Echo Memory, and score what it retrieved.

LongMemEval_S is 500 questions, each with its own haystack of about 50 chat
sessions - roughly 115k tokens of history per question, 246,930 turns in total.
The sessions holding the answer are named in `answer_session_ids`, and the
individual turns that carry it are flagged `has_answer`.

Same measurement as `locomo-bench.py`, and the same caveat, which matters more
here because LongMemEval's published numbers are the ones people quote. Those
are QA accuracy, judged by a model. This is retrieval: whether the turn that
holds the answer came back at all. It is a **ceiling on** QA accuracy and is
not comparable to a published LongMemEval number.

Two recalls are reported because the benchmark supports both and they say
different things. Session recall asks whether the right conversation surfaced,
which is what a reader would then have to read. Turn recall asks whether the
specific line carrying the answer surfaced, which is what "retrieval worked"
should mean for a store that returns facts rather than documents.

    curl -sLo longmemeval_s.json \
      https://huggingface.co/datasets/xiaowu0162/longmemeval/resolve/main/longmemeval_s

    ECHO_MEMORY_DATABASE_URL=postgresql://.../lme_bench \
    ECHO_MEMORY_USER_ID=bench ECHO_MEMORY_AGENT_ID=bench \
        python scripts/longmemeval-bench.py longmemeval_s.json [instances]

Point it at a scratch database. The full run writes 246,930 facts across 500
scopes and takes hours; pass an instance count to run a prefix instead, and say
which you ran when you quote the result.
"""

from __future__ import annotations

import json
import statistics
import sys
import time

from echo_memory.infra.config import load_config
from echo_memory.infra.db import connect
from echo_memory.ingestion.embeddings import LocalEmbedder
from echo_memory.ingestion.write_episode import write_episode
from echo_memory.retrieval.query_memory import query_memory

KS = [1, 5, 10, 20, 30]


def turns_of(instance: dict):
    """Yield (session_id, date, index, role, content, is_gold_turn).

    One haystack entry per question, so each instance gets its own scope. Dates
    ride along because a third of LongMemEval is temporal reasoning, and a store
    that never recorded when something was said cannot answer those at any k.
    """
    dates = instance.get("haystack_dates") or []
    ids = instance["haystack_session_ids"]
    for position, (session_id, session) in enumerate(
        zip(ids, instance["haystack_sessions"])
    ):
        when = dates[position] if position < len(dates) else ""
        for index, turn in enumerate(session):
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            yield (
                session_id, when, index,
                turn.get("role") or "speaker", content,
                bool(turn.get("has_answer")),
            )


def ingest(conn, embedder, instances: list[dict]) -> int:
    """One fact per turn, keyed so scoring can find it again.

    Both mentions are asserted as new for the reasons spelled out in
    locomo-bench.py: without the utterance assertion the turns supersede one
    another, and without the speaker assertion a name that embeds near another
    is flagged ambiguous and its facts are deferred rather than written, with
    nothing raised. An exact name match still overrides the assertion.
    """
    written = 0
    started = time.time()
    for instance in instances:
        group = f"lme:{instance['question_id']}"
        for session_id, when, index, role, content, _gold in turns_of(instance):
            key = f"{session_id}#{index}"
            body = f"the {role} said on {when}: {content}" if when else f"the {role} said: {content}"
            write_episode(
                conn, group, session_id,
                [{"name": role, "type": "speaker"},
                 {"name": key, "type": "utterance"}],
                [{"source": role, "target": key, "relation_type": "said",
                  "fact": body, "confidence": "extracted"}],
                {key: {"resolved_to": "new"}, role: {"resolved_to": "new"}},
                embedder,
                project=key,
                agent_id="longmemeval",
            )
            written += 1
            if written % 1000 == 0:
                print(f"  {written:,} turns  "
                      f"{written / (time.time() - started):.0f}/s", flush=True)
    return written


def score(conn, embedder, instances: list[dict]) -> list[dict]:
    rows = []
    for instance in instances:
        group = f"lme:{instance['question_id']}"
        gold_sessions = {str(s) for s in instance.get("answer_session_ids") or []}
        gold_turns = {
            f"{session_id}#{index}"
            for session_id, _when, index, _role, _content, is_gold in turns_of(instance)
            if is_gold
        }
        if not gold_sessions:
            continue
        found = query_memory(conn, group, instance["question"], max(KS), embedder)
        got = [
            (f.get("provenance") or {}).get("project") or ""
            for f in found.get("facts", [])
        ]
        row = {"type": instance.get("question_type")}
        for k in KS:
            top = got[:k]
            sessions = {key.split("#")[0] for key in top}
            row[f"session@{k}"] = len(sessions & gold_sessions) / len(gold_sessions)
            row[f"turn@{k}"] = (
                len(set(top) & gold_turns) / len(gold_turns) if gold_turns else 0.0
            )
            row[f"hit@{k}"] = 1.0 if sessions & gold_sessions else 0.0
        rows.append(row)
    return rows


def render(rows: list[dict]) -> str:
    def line(label: str, subset: list[dict]) -> str:
        if not subset:
            return ""
        parts = [f"n={len(subset):>4}"]
        parts += [
            f"session@{k} {statistics.mean(r[f'session@{k}'] for r in subset):.3f}"
            for k in (5, 10, 30)
        ]
        parts += [
            f"turn@{k} {statistics.mean(r[f'turn@{k}'] for r in subset):.3f}"
            for k in (10, 30)
        ]
        return f"{label:<26} " + "  ".join(parts)

    out = ["", line("overall", rows)]
    for kind in sorted({r["type"] for r in rows if r["type"]}):
        out.append(line(kind, [r for r in rows if r["type"] == kind]))
    out += [
        "",
        "session@k is the share of answer-bearing sessions represented in the top k;",
        "turn@k the share of the individual turns flagged has_answer. Retrieval, not",
        "QA accuracy: a ceiling on what a reader could answer from what came back.",
    ]
    return "\n".join(out)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    with open(sys.argv[1]) as handle:
        instances = json.load(handle)
    if len(sys.argv) > 2:
        instances = instances[: int(sys.argv[2])]

    conn = connect(load_config().database_url)
    embedder = LocalEmbedder()
    embedder.embed("warm")

    started = time.time()
    written = ingest(conn, embedder, instances)
    print(f"ingested {written:,} turns across {len(instances)} scopes "
          f"in {time.time() - started:.0f}s")

    rows = score(conn, embedder, instances)
    print(render(rows))
    print(f"\n{len(rows):,} questions scored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
