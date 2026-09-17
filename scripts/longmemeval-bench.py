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
        python scripts/longmemeval-bench.py longmemeval_s.json [instances] [results.jsonl]

Point it at a scratch database. The full run writes 246,930 facts across 500
scopes and takes hours, and write throughput decays as the database grows, so
budget generously. Pass an instance count to run a prefix instead, and say
which you ran when you quote the result.

**It is safe to rerun.** A scope already holding exactly its expected number of
facts is scored without being rewritten, so a run killed at hour three resumes
rather than starting over. Pass a results path to have each scored question
appended as it happens.
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


def instances_in(path: str, limit: int = 0):
    """Yield one instance at a time, so only one is ever resident.

    Worth a modest amount and no more, and the measurement is here so nobody
    credits it with more: `json.load` on this file peaks at 0.92GB, this peaks
    at 0.56GB. The first full attempt was killed for memory at 27,394 of
    246,930 turns and this is NOT why. Python RSS during ingest is flat at
    1.3GB across thousands of turns, so the pressure was elsewhere on the
    machine. What protects a long run is `already_ingested` below, not this.
    """
    with open(path) as handle:
        text = handle.read()
    decoder = json.JSONDecoder()
    at = text.index("[") + 1
    yielded = 0
    while True:
        while at < len(text) and text[at] in " \t\r\n,":
            at += 1
        if at >= len(text) or text[at] == "]":
            return
        instance, at = decoder.raw_decode(text, at)
        yield instance
        yielded += 1
        if limit and yielded >= limit:
            return


# write_episode rejects a fact longer than MAX_STRING_LEN (4000 characters) by
# returning {"error": ...} rather than raising, so a caller that does not read
# the return value counts it as written. LongMemEval has long assistant turns
# and they are exactly the ones most likely to carry an answer, so they are
# split rather than dropped. The prefix costs a little of the budget.
MAX_FACT = 3500


def chunks(text: str, size: int = MAX_FACT) -> list[str]:
    """Split on a paragraph or sentence boundary where there is one nearby, so
    a chunk is still something a reader could act on."""
    if len(text) <= size:
        return [text]
    out = []
    while len(text) > size:
        window = text[:size]
        # The END of the boundary, not its start. Cutting at the index of ". "
        # drops the full stop into the gap between two chunks, which is how the
        # first version of this silently ate a character per split.
        candidates = [
            found + len(marker)
            for marker in ("\n\n", ". ")
            if (found := window.rfind(marker)) != -1
        ]
        cut = max(candidates, default=0)
        if cut < size // 2:
            cut = size
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return out


def turns_of(instance: dict):
    """Yield (gold_id, node_name, date, role, content, is_gold_turn).

    `gold_id` is the logical turn identity, `session_id#index`, which is what
    scoring compares against. `node_name` is the entity the fact points at and
    has to be unique within the scope, which `gold_id` is not: a haystack can
    list the same session id twice, and a long turn becomes several facts. Two
    facts sharing a target would supersede one another rather than coexist,
    because a fact is an edge keyed by (source, target, relation_type).

    Dates ride along because a third of LongMemEval is temporal reasoning, and
    a store that never recorded when something was said cannot answer those at
    any k.
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
            role = turn.get("role") or "speaker"
            gold = bool(turn.get("has_answer"))
            for part, piece in enumerate(chunks(content)):
                yield (
                    f"{session_id}#{index}",
                    f"turn {position}.{index}.{part}",
                    when, role, piece, gold,
                )


def already_ingested(conn, group: str, expected: int) -> bool:
    """Has this scope been fully written by an earlier attempt?

    A full run is several hours and the first one was killed near its end,
    losing everything. Each instance is a self contained scope, so a rerun can
    skip the ones that finished and pick up where it stopped. The count has to
    match exactly: a scope interrupted midway is rewritten rather than trusted,
    because a partial haystack would score as a retrieval failure and look like
    a result.
    """
    row = conn.execute(
        "SELECT count(*) FROM public.fact_embedding WHERE group_id = %s", (group,)
    ).fetchone()
    return bool(row) and row[0] == expected


def ingest(conn, embedder, instance: dict, written: int, started: float) -> int:
    """One fact per turn, keyed so scoring can find it again.

    Both mentions are asserted as new for the reasons spelled out in
    locomo-bench.py: without the utterance assertion the turns supersede one
    another, and without the speaker assertion a name that embeds near another
    is flagged ambiguous and its facts are deferred rather than written, with
    nothing raised. An exact name match still overrides the assertion.
    """
    group = f"lme:{instance['question_id']}"
    for gold_id, node, when, role, content, _gold in turns_of(instance):
        body = (
            f"the {role} said on {when}: {content}" if when
            else f"the {role} said: {content}"
        )
        result = write_episode(
            conn, group, gold_id.split("#")[0],
            [{"name": role, "type": "speaker"},
             {"name": node, "type": "utterance"}],
            [{"source": role, "target": node, "relation_type": "said",
              "fact": body, "confidence": "extracted"}],
            {node: {"resolved_to": "new"}, role: {"resolved_to": "new"}},
            embedder,
            project=gold_id,
            agent_id="longmemeval",
        )
        if not result.get("edges_created"):
            # Never silently. A benchmark that quietly drops the turns it finds
            # awkward is measuring a corpus nobody has.
            raise SystemExit(
                f"write refused for {node} in {group}: "
                f"{result.get('error') or result}"
            )
        written += 1
        if written % 1000 == 0:
            print(f"  {written:,} turns  "
                  f"{written / (time.time() - started):.0f}/s", flush=True)
    return written


def score(conn, embedder, instance: dict) -> dict | None:
    group = f"lme:{instance['question_id']}"
    gold_sessions = {str(s) for s in instance.get("answer_session_ids") or []}
    gold_turns = {
        gold_id
        for gold_id, _node, _when, _role, _content, is_gold in turns_of(instance)
        if is_gold
    }
    if not gold_sessions:
        return None
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
    return row


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
    path = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    results = sys.argv[3] if len(sys.argv) > 3 else ""

    conn = connect(load_config().database_url)
    embedder = LocalEmbedder()
    embedder.embed("warm")

    # Ingest and score one instance at a time rather than in two passes. Each
    # instance is a self contained haystack, so nothing is lost by finishing
    # with it before reading the next, and two things are gained: peak memory
    # is one haystack, and a run that dies at hour three has scored everything
    # it ingested instead of nothing.
    rows: list[dict] = []
    written = 0
    scopes = 0
    skipped = 0
    started = time.time()
    for instance in instances_in(path, limit):
        group = f"lme:{instance['question_id']}"
        expected = sum(1 for _ in turns_of(instance))
        if already_ingested(conn, group, expected):
            skipped += 1
        else:
            written = ingest(conn, embedder, instance, written, started)
        row = score(conn, embedder, instance)
        scopes += 1
        if row:
            rows.append(row)
            if results:
                # Written as we go, so a killed run keeps what it scored.
                with open(results, "a") as handle:
                    handle.write(json.dumps({"question_id": instance["question_id"],
                                             **row}) + "\n")
        if scopes % 25 == 0:
            print(f"  {scopes} scopes scored, {written:,} turns written, "
                  f"{skipped} already present", flush=True)

    print(f"\ningested {written:,} turns across {scopes} scopes "
          f"({skipped} already present) in {time.time() - started:.0f}s")
    print(render(rows))
    print(f"\n{len(rows):,} questions scored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
