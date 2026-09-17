#!/usr/bin/env python3
"""Run LoCoMo against Echo Memory, and score what it retrieved.

LoCoMo is ten very long conversations between two people, with 1,986 questions
whose gold answers cite the exact dialogue turns that support them. Published
LoCoMo results are QA accuracy: a model reads what memory returned, writes an
answer, and a second model judges it. That needs two model keys and makes the
number partly a property of those models.

This measures the layer underneath, which needs no model at all: given every
turn of the conversation, does the store put the cited turn in front of the
reader? A system that cannot retrieve the evidence cannot answer the question,
so this is a **ceiling on** QA accuracy rather than a substitute for it, and it
is not comparable to anybody's published QA number. Reporting it as one would
be dishonest in the specific way that is easy to get away with.

It is also generous in one direction and harsh in another, and both are worth
saying. Generous: the gold turn is in the store, because every turn is. Harsh:
feeding raw dialogue skips the step this product deliberately pushes to the
calling agent, which is deciding what in a conversation was worth remembering.
So the number describes retrieval over unfiltered input, which is the worst
case for a store built to hold facts somebody chose.

    curl -sLO https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json

    ECHO_MEMORY_DATABASE_URL=postgresql://.../locomo_bench \
    ECHO_MEMORY_USER_ID=bench ECHO_MEMORY_AGENT_ID=bench \
        python scripts/locomo-bench.py locomo10.json

Point it at a scratch database. It writes 5,882 facts.
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
CATEGORIES = {
    1: "multi hop", 2: "temporal", 3: "open domain",
    4: "single hop", 5: "adversarial",
}


def sessions(conversation: dict) -> list[str]:
    return sorted(
        (
            k for k in conversation
            if k.startswith("session_") and not k.endswith("date_time")
        ),
        key=lambda k: int(k.split("_")[1]),
    )


def ingest(conn, embedder, samples: list[dict]) -> int:
    """One fact per dialogue turn, with the turn's own dia_id in the fact's
    project field so scoring can check whether the gold turn came back.

    Both entity mentions are asserted as new, and both assertions are load
    bearing. Without the utterance one the turns supersede each other: a fact
    is an edge keyed by (source, target, relation_type), so
    `speaker --said--> session` writes one fact per session, and 419 turns
    became 18. Without the speaker one, two names that embed near each other
    are flagged ambiguous and every fact touching the second is DEFERRED rather
    than written, with nothing raised - Tim and John in conv-43, which cost 344
    of 680 turns and looked like a successful ingest. An exact name match
    overrides the assertion, so a speaker's second turn still resolves onto the
    node their first one made.
    """
    written = 0
    started = time.time()
    for sample in samples:
        group = f"locomo:{sample['sample_id']}"
        conversation = sample["conversation"]
        for key in sessions(conversation):
            when = conversation.get(f"{key}_date_time", "")
            for turn in conversation[key]:
                text = (turn.get("text") or "").strip()
                dia = turn.get("dia_id") or ""
                if not text or not dia:
                    continue
                speaker = turn.get("speaker") or "someone"
                # The date rides in the fact text on purpose: a sixth of
                # LoCoMo's questions are temporal, and a store that never
                # recorded when something was said cannot answer them at any k.
                body = (
                    f"{speaker} said on {when}: {text}" if when
                    else f"{speaker} said: {text}"
                )
                write_episode(
                    conn, group, f"{sample['sample_id']}-{key}",
                    [{"name": speaker, "type": "person"},
                     {"name": dia, "type": "utterance"}],
                    [{"source": speaker, "target": dia, "relation_type": "said",
                      "fact": body, "confidence": "extracted"}],
                    {dia: {"resolved_to": "new"},
                     speaker: {"resolved_to": "new"}},
                    embedder,
                    project=dia,
                    agent_id="locomo",
                )
                written += 1
                if written % 500 == 0:
                    print(f"  {written} turns  "
                          f"{written / (time.time() - started):.0f}/s", flush=True)
    return written


def score(conn, embedder, samples: list[dict]) -> list[dict]:
    rows = []
    for sample in samples:
        group = f"locomo:{sample['sample_id']}"
        for question in sample.get("qa", []):
            gold = {str(e) for e in (question.get("evidence") or [])}
            if not gold:
                # Four of LoCoMo's questions cite no turn. A question with no
                # gold cannot be scored either way, and counting it as a miss
                # would quietly deflate every number here.
                continue
            found = query_memory(conn, group, question["question"], max(KS), embedder)
            got = [
                (f.get("provenance") or {}).get("project") or ""
                for f in found.get("facts", [])
            ]
            first = next((i + 1 for i, d in enumerate(got) if d in gold), None)
            row = {"category": question.get("category"), "rr": 1 / first if first else 0.0}
            for k in KS:
                top = set(got[:k])
                row[f"recall@{k}"] = len(top & gold) / len(gold)
                row[f"hit@{k}"] = 1.0 if top & gold else 0.0
            rows.append(row)
    return rows


def render(rows: list[dict]) -> str:
    def line(label: str, subset: list[dict]) -> str:
        if not subset:
            return ""
        parts = [f"n={len(subset):>5}"]
        parts += [
            f"recall@{k} {statistics.mean(r[f'recall@{k}'] for r in subset):.3f}"
            for k in KS
        ]
        parts.append(f"hit@10 {statistics.mean(r['hit@10'] for r in subset):.3f}")
        parts.append(f"MRR {statistics.mean(r['rr'] for r in subset):.3f}")
        return f"{label:<14} " + "  ".join(parts)

    out = ["", line("overall", rows)]
    for code in sorted({r["category"] for r in rows if r["category"] is not None}):
        out.append(line(CATEGORIES.get(code, str(code)),
                        [r for r in rows if r["category"] == code]))
    out += [
        "",
        "recall@k is the share of a question's cited turns that came back in the top k.",
        "This is retrieval, not QA accuracy: a ceiling on what any reader could answer",
        "from what memory returned, and not comparable to a published LoCoMo QA number.",
    ]
    return "\n".join(out)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    with open(sys.argv[1]) as handle:
        samples = json.load(handle)
    if len(sys.argv) > 2:
        samples = samples[: int(sys.argv[2])]

    conn = connect(load_config().database_url)
    embedder = LocalEmbedder()
    embedder.embed("warm")      # the first call loads the model; keep it out of the rate

    started = time.time()
    written = ingest(conn, embedder, samples)
    print(f"ingested {written:,} turns in {time.time() - started:.0f}s")

    started = time.time()
    rows = score(conn, embedder, samples)
    print(render(rows))
    print(f"\n{len(rows):,} questions scored in {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
