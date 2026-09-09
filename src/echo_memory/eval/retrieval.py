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

**Query shape decides the answer, so it is not a detail.** The first version of
this harness asked every question as "<source> <target>". Once entity names
were embedded into each fact, that query became a literal substring of the text
it was scoring against - maximum leakage - and it inverted a real conclusion:
under it, dropping the lexical channel measured +0.112 MRR and looked like a
significant win. On queries with the entity names removed the same change is
-0.082, significantly WORSE. One default query shape produced two opposite
answers about the same code.

So shapes are plural and named, and the leaky one is labelled:

  entity_pair   both names. Maximum leakage now that names are embedded. Kept
                because it is the entity-centric lookup an agent really does
                make, but never read alone.
  entity_single one name. The realistic middle - a question usually names one
                of the things it is about, and half the prepended string.
  prose         the fact's own words with both entity names stripped. No
                overlap with what was prepended, so nothing can leak; also the
                least realistic, since nobody queries in the target's prose.

**And MRR is a mean, so it has a standard error.** At n=219 with sd ~0.35 the
SE is ~0.023, which makes any difference under ~0.047 indistinguishable from
zero. Differences of 0.001 to 0.01 were reported as findings before this was
computed. Every comparison now carries a paired bootstrap interval, and
`compare` says plainly when a difference is noise.
"""

from __future__ import annotations

import json
import random
import re
import statistics
from dataclasses import dataclass, field

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.retrieval.query_memory import query_memory

# Roughly 4 characters per token for English prose. The same constant the read
# accounting uses; exactness does not matter because it is only ever compared
# against itself across configurations.
CHARS_PER_TOKEN = 4

DEFAULT_TOP_K = 10

# Resamples for the bootstrap interval. Enough that the 2.5th and 97.5th
# percentiles are stable to the third decimal, which is finer than any
# difference worth acting on.
BOOTSTRAP_RESAMPLES = 5000

# Query shapes, most leaky first. See the module docstring.
SHAPE_ENTITY_PAIR = "entity_pair"
SHAPE_ENTITY_SINGLE = "entity_single"
SHAPE_PROSE = "prose"
SHAPES = (SHAPE_ENTITY_PAIR, SHAPE_ENTITY_SINGLE, SHAPE_PROSE)

# Words of the fact to keep for a prose query. Long enough to carry the
# subject, short enough that it is a question rather than the answer.
PROSE_WORDS = 14


@dataclass(frozen=True)
class Case:
    """One retrieval question and its known answer."""

    query: str
    gold_edge_id: str
    gold_fact: str
    shape: str = SHAPE_ENTITY_PAIR


@dataclass
class Result:
    name: str
    cases: int = 0
    hits_at: dict[int, int] = field(default_factory=lambda: {1: 0, 3: 0, 5: 0, 10: 0})
    reciprocal_ranks: list[float] = field(default_factory=list)
    returned_chars: list[int] = field(default_factory=list)
    empty: int = 0
    shape: str = SHAPE_ENTITY_PAIR

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

    @property
    def mrr_stderr(self) -> float:
        """MRR is a mean over cases, so it has one.

        At n=219 with sd around 0.35 this is about 0.023, which makes any
        difference under roughly 0.047 indistinguishable from zero. Differences
        of 0.001 to 0.01 were reported as findings before anyone computed it.
        """
        if len(self.reciprocal_ranks) < 2:
            return 0.0
        return statistics.stdev(self.reciprocal_ranks) / len(self.reciprocal_ranks) ** 0.5


def compare(baseline: Result, variant: Result, resamples: int = BOOTSTRAP_RESAMPLES,
            seed: int = 7) -> dict:
    """Is variant actually different from baseline, or is it noise?

    Paired, because both scored the same cases in the same order: the variance
    that matters is that of the per-case DIFFERENCE, not of either mean. Two
    configurations agreeing on 200 of 219 cases have a far tighter interval than
    their separate standard errors suggest, and an unpaired test would call a
    real improvement noise.

    Bootstrap rather than a t-test: reciprocal ranks are neither normal nor
    continuous - they are 1, 1/2, 1/3 ... 0, with a heavy spike at 0 - so
    resampling makes no distributional claim that the data would violate.
    """
    if len(baseline.reciprocal_ranks) != len(variant.reciprocal_ranks):
        raise ValueError("compare needs both configurations scored on the same cases")

    diffs = [v - b for v, b in zip(variant.reciprocal_ranks, baseline.reciprocal_ranks,
                                   strict=True)]
    if not diffs:
        return {"delta": 0.0, "low": 0.0, "high": 0.0, "significant": False}

    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(
        sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples)
    )
    low = means[int(0.025 * resamples)]
    high = means[int(0.975 * resamples)]
    return {
        "delta": sum(diffs) / n,
        "low": low,
        "high": high,
        # Excludes zero at 95%. Not "true", just "not obviously nothing".
        "significant": low > 0 or high < 0,
    }


def _prose_query(fact: str, source: str, target: str) -> str:
    """The fact's own words with both entity names removed.

    Removing them is the point: entity names are embedded into every fact, so a
    query containing them overlaps the text being scored. With them gone
    nothing can leak, and what is left measures whether the ranker finds a fact
    from its subject matter rather than from a shared literal.
    """
    stripped = fact
    for name in (source, target):
        if name:
            stripped = re.sub(re.escape(name), " ", stripped, flags=re.IGNORECASE)
    return " ".join(stripped.split()[:PROSE_WORDS])


def build_cases(
    conn, group_id: str, limit: int | None = None, shape: str = SHAPE_ENTITY_PAIR
) -> list[Case]:
    """One case per fact whose two entities have different names.

    Self-loops are skipped. A fact from a node to itself gives a query of one
    repeated word, which measures nothing about ranking and is over-represented
    in this store because agents reach for a self-edge when a fact has no
    natural second entity.

    `shape` decides what the question looks like, and it decides the answer -
    see the module docstring. Defaults to entity_pair for continuity with
    earlier numbers, but a conclusion drawn from it alone is not safe.
    """
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {SHAPES}, got {shape!r}")
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
        if shape == SHAPE_ENTITY_PAIR:
            query = f"{source} {target}"
        elif shape == SHAPE_ENTITY_SINGLE:
            query = source
        else:
            query = _prose_query(text, source, target)
        if not query.strip():
            continue
        cases.append(
            Case(query=query, gold_edge_id=str(edge_id), gold_fact=text, shape=shape)
        )
    return cases[:limit] if limit else cases


def run(conn, group_id: str, embedder, cases: list[Case], name: str, **kwargs) -> Result:
    """Score one configuration over the cases. kwargs go straight to
    query_memory, so a configuration IS its keyword arguments."""
    result = Result(name=name, shape=cases[0].shape if cases else SHAPE_ENTITY_PAIR)
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


SHAPE_NOTES = {
    SHAPE_ENTITY_PAIR: "both entity names - LEAKY: names are embedded into every fact",
    SHAPE_ENTITY_SINGLE: "one entity name - the realistic shape",
    SHAPE_PROSE: "the fact's words, entity names stripped - cannot leak",
}


def render(results: list[Result]) -> str:
    """A table per query shape, with each row's difference from the first.

    Deltas and intervals rather than bare means, because a bare mean is what
    let a 0.001 difference be written down as a finding. The first row of each
    shape is the baseline the rest are measured against.
    """
    if not results:
        return "no configurations run"

    lines: list[str] = []
    by_shape: dict[str, list[Result]] = {}
    for r in results:
        by_shape.setdefault(r.shape, []).append(r)

    for shape in SHAPES:
        group = by_shape.get(shape)
        if not group:
            continue
        baseline = group[0]
        lines.append("")
        lines.append(f"{shape}  ({SHAPE_NOTES[shape]})")
        head = (
            f"  {'configuration':<26}{'R@1':>7}{'R@3':>7}{'R@10':>7}"
            f"{'MRR':>8}{'ΔMRR':>9}{'95% CI':>20}{'tokens':>9}"
        )
        lines.append(head)
        lines.append("  " + "-" * (len(head) - 2))
        for r in group:
            if r is baseline:
                delta_cell, ci_cell = f"{'—':>9}", f"{'baseline':>20}"
            else:
                c = compare(baseline, r)
                delta_cell = f"{c['delta']:>+9.4f}"
                marker = "" if c["significant"] else " ?"
                ci_cell = f"[{c['low']:>+7.4f},{c['high']:>+7.4f}]{marker:>2}"
            lines.append(
                f"  {r.name:<26}"
                f"{r.recall(1):>7.3f}{r.recall(3):>7.3f}{r.recall(10):>7.3f}"
                f"{r.mrr:>8.3f}{delta_cell}{ci_cell:>20}{r.mean_tokens:>9,}"
            )
        lines.append(
            f"  n={baseline.cases}, SE(MRR)≈{baseline.mrr_stderr:.3f}, "
            f"so anything under ~{2 * baseline.mrr_stderr:.3f} is inside 2 SE of zero"
        )

    lines.append("")
    lines.append("? marks an interval that includes zero: the difference is noise.")
    lines.append("Absolute values describe this store only. Compare rows, not numbers.")
    return "\n".join(lines)
