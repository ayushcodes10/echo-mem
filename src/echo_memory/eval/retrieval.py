"""Does a retrieval change actually help? Measure it.

Every tuning decision in this project so far has been argued rather than
demonstrated. `COSINE_FLOOR` was picked, then measured a year of usage later to
be sitting inside the noise. `k=60` and `LIST_DEPTH=50` were written down as
"low-leverage" when in fact the fusion had never had two lists to fuse. The
common cause is that there was no way to tell whether a change was an
improvement, so nobody could be wrong out loud.

**The labels are free.** A fact is an edge between two named entities, and the
question an agent actually asks is entity-shaped - "what do I know about
updateSquad" - so the entity names make a query and the fact they connect is
the gold answer. That is not circular: the query is two short labels, the gold
is a sentence of prose that shares only some of their words, and the ranker has
to find it among every other fact in the store.

It is also not a benchmark. It measures one store against itself, so the
absolute numbers mean nothing outside it. What it is for is A/B: run two
configurations over the same cases and see which retrieves better, which is the
question that was previously unanswerable.

Three metrics, and the second two matter more than the first.

  recall@k   did the gold fact come back at all
  MRR        how high, averaged - moving a hit from rank 8 to rank 2 shows here
             and is invisible to recall@10
  tokens     what the answer cost. A configuration that finds everything by
             returning everything is not better, and this is the number that
             says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.retrieval.query_memory import query_memory

# Roughly 4 characters per token for English prose. The same constant the read
# accounting uses; exactness does not matter because it is only ever compared
# against itself across configurations.
CHARS_PER_TOKEN = 4

DEFAULT_TOP_K = 10


@dataclass(frozen=True)
class Case:
    """One retrieval question and its known answer."""

    query: str
    gold_edge_id: str
    gold_fact: str


@dataclass
class Result:
    name: str
    cases: int = 0
    hits_at: dict[int, int] = field(default_factory=lambda: {1: 0, 3: 0, 5: 0, 10: 0})
    reciprocal_ranks: list[float] = field(default_factory=list)
    returned_chars: list[int] = field(default_factory=list)
    empty: int = 0

    def recall(self, k: int) -> float:
        return self.hits_at[k] / self.cases if self.cases else 0.0

    @property
    def mrr(self) -> float:
        return sum(self.reciprocal_ranks) / self.cases if self.cases else 0.0

    @property
    def mean_tokens(self) -> int:
        if not self.returned_chars:
            return 0
        return int(sum(self.returned_chars) / len(self.returned_chars) / CHARS_PER_TOKEN)

    @property
    def abstention_rate(self) -> float:
        return self.empty / self.cases if self.cases else 0.0


def build_cases(conn, group_id: str, limit: int | None = None) -> list[Case]:
    """One case per fact whose two entities have different names.

    Self-loops are skipped. A fact from a node to itself gives a query of one
    repeated word, which measures nothing about ranking and is over-represented
    in this store because agents reach for a self-edge when a fact has no
    natural second entity.
    """
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (a:Node)-[e:FACT]->(b:Node)
            WHERE e.group_id = $gid AND e.t_invalid IS NULL
            RETURN id(e), a.name, b.name, e.fact
        $$, %s) AS (edge_id agtype, a agtype, b agtype, fact agtype)""",
        (json.dumps({"gid": group_id}),),
    ).fetchall()

    cases: list[Case] = []
    for edge_id, a, b, fact in rows:
        source = str(a).strip('"')
        target = str(b).strip('"')
        text = str(fact).strip('"')
        if not source or not target or source == target:
            continue
        cases.append(
            Case(query=f"{source} {target}", gold_edge_id=str(edge_id), gold_fact=text)
        )
    return cases[:limit] if limit else cases


def run(conn, group_id: str, embedder, cases: list[Case], name: str, **kwargs) -> Result:
    """Score one configuration over the cases. kwargs go straight to
    query_memory, so a configuration IS its keyword arguments."""
    result = Result(name=name)
    for case in cases:
        response = query_memory(
            conn, group_id, case.query, DEFAULT_TOP_K, embedder, **kwargs
        )
        facts = response.get("facts") or []
        result.cases += 1
        if not facts:
            result.empty += 1
        result.returned_chars.append(sum(len(f.get("fact") or "") for f in facts))

        rank = None
        for i, fact in enumerate(facts, start=1):
            if str(fact.get("fact_id")) == case.gold_edge_id:
                rank = i
                break
        if rank is None:
            result.reciprocal_ranks.append(0.0)
            continue
        result.reciprocal_ranks.append(1.0 / rank)
        for k in result.hits_at:
            if rank <= k:
                result.hits_at[k] += 1
    return result


def render(results: list[Result]) -> str:
    """A table, with the shipping configuration first so the rest read as
    deltas against it."""
    if not results:
        return "no configurations run"

    head = (
        f"{'configuration':<28}{'R@1':>7}{'R@3':>7}{'R@5':>7}{'R@10':>7}"
        f"{'MRR':>8}{'tokens':>9}{'empty':>8}"
    )
    lines = [head, "-" * len(head)]
    for r in results:
        lines.append(
            f"{r.name:<28}"
            f"{r.recall(1):>7.3f}{r.recall(3):>7.3f}{r.recall(5):>7.3f}{r.recall(10):>7.3f}"
            f"{r.mrr:>8.3f}{r.mean_tokens:>9,}{r.abstention_rate:>8.1%}"
        )
    lines.append("")
    lines.append(f"{results[0].cases} cases, one per fact connecting two distinct entities")
    lines.append("Absolute values describe this store only. Compare rows, not numbers.")
    return "\n".join(lines)
