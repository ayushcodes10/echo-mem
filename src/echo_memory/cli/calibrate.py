"""echo-memory calibrate: what the store's own judgements say about the
thresholds entity resolution is built on.

resolution.py has described LOW_THRESHOLD and HIGH_THRESHOLD as "placeholders
pending real calibration against the v1a trial's data" since they were written.
The trial has now produced that data - 155 pairs a human confirmed distinct, a
handful confirmed the same - so this is the calibration, as a command rather
than a one-off script, because a number nobody can recompute is a number nobody
should act on.

The answer it gives is mostly negative, which is the point. On this store the
two classes overlap almost completely and the AUC confidence interval includes
0.5, so cosine similarity between entity names is not demonstrably better than
chance at telling a duplicate from a distinct entity. That is worth knowing
before anyone tunes a threshold on it.

**The negatives are censored.** Every pair anyone has ever judged was offered
for review, and a pair is only offered when it already scores above
LOW_THRESHOLD. So this data can say what fraction of surfaced pairs are wrong -
precision - and can say nothing at all about the duplicates sitting below the
bar that were never shown to anyone. Recall is not estimable from it, and no
amount of re-analysis changes that; only labelling pairs from below the bar
does, which is what --sample-below is for.
"""

from __future__ import annotations

import json
import math
import random

from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.ingestion.resolution import HIGH_THRESHOLD, LOW_THRESHOLD

# Enough resamples that the interval is stable to the third decimal, which is
# further than anything here should be read to anyway.
BOOTSTRAP_RESAMPLES = 5000
SEED = 7

# Below this many positives the interval is so wide that quoting a point
# estimate is misleading on its own.
FEW_POSITIVES = 10

OPERATING_POINTS = (0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.92, 0.95)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _embeddings(conn, group_ids: list[str]) -> dict[str, list[float]]:
    rows = conn.execute(
        """SELECT node_id::text, embedding::text FROM public.node_embedding
            WHERE group_id = ANY(%s)""",
        (group_ids,),
    ).fetchall()
    return {node_id: json.loads(vector) for node_id, vector in rows}


def _names(conn, group_ids: list[str]) -> dict[str, str]:
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE n.group_id IN $gids RETURN id(n), n.name
        $$, %s) AS (i agtype, n agtype)""",
        (json.dumps({"gids": group_ids}),),
    ).fetchall()
    return {str(i): str(n).strip('"') for i, n in rows}


def negatives(conn, group_ids: list[str], embeddings, names) -> list[dict]:
    """Pairs a human looked at and called distinct entities."""
    rows = conn.execute(
        """SELECT node_ids FROM public.trial_observation
            WHERE kind = 'not_duplicate' AND node_ids IS NOT NULL
              AND group_id = ANY(%s)""",
        (group_ids,),
    ).fetchall()
    out = []
    for (pair,) in rows:
        a, b = pair
        if a in embeddings and b in embeddings:
            out.append({
                "a": names.get(a, a), "b": names.get(b, b),
                "similarity": _cosine(embeddings[a], embeddings[b]),
            })
    return out


def positives(conn, group_ids: list[str], embedder) -> list[dict]:
    """Name pairs confirmed to mean the same entity.

    Two sources, and the second is the only one that has ever produced
    anything. A `duplicate_node` observation is a human saying two nodes are
    one entity. An alias is the same statement made earlier and acted on: the
    mention was absorbed into the node, so the node's name and that alias are a
    confirmed-same pair. The alias has no node of its own, so its similarity is
    computed from the embedder rather than read from a stored vector - the same
    number a mention would produce arriving fresh, which is the case that
    matters.
    """
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (n:Node) WHERE n.group_id IN $gids AND n.aliases IS NOT NULL
            RETURN n.name, n.aliases
        $$, %s) AS (n agtype, a agtype)""",
        (json.dumps({"gids": group_ids}),),
    ).fetchall()

    out = []
    for name, aliases in rows:
        node_name = str(name).strip('"')
        for alias in json.loads(str(aliases)) or []:
            alias = str(alias)
            # A node records itself among its aliases; that pair is not
            # evidence of anything.
            if alias.lower() == node_name.lower():
                continue
            out.append({
                "a": node_name, "b": alias,
                "similarity": _cosine(embedder.embed(node_name), embedder.embed(alias)),
            })
    return out


def auc(pos: list[float], neg: list[float]) -> float:
    """Mann-Whitney: the probability a random confirmed-duplicate scores above
    a random confirmed-distinct pair. 0.5 is a coin."""
    if not pos or not neg:
        return float("nan")
    wins = sum(
        1.0 if p > n else 0.5 if p == n else 0.0
        for p in pos
        for n in neg
    )
    return wins / (len(pos) * len(neg))


def auc_interval(pos: list[float], neg: list[float], seed: int = SEED) -> tuple[float, float]:
    """Percentile bootstrap over both classes. Resampling the positives is what
    makes the interval honest: with five of them, most of the width comes from
    not knowing whether those five are typical."""
    if len(pos) < 2 or len(neg) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    draws = sorted(
        auc(
            [rng.choice(pos) for _ in pos],
            [rng.choice(neg) for _ in neg],
        )
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    lo = draws[int(0.025 * len(draws))]
    hi = draws[min(int(0.975 * len(draws)), len(draws) - 1)]
    return (lo, hi)


def operating_points(pos: list[float], neg: list[float]) -> list[dict]:
    """What each candidate threshold would do to the review queue.

    `recall` is over the confirmed duplicates only, and they are few. `reviews`
    is the honest cost line: the number of pairs a person has to look at to
    find them.
    """
    points = []
    for t in OPERATING_POINTS:
        kept = sum(1 for p in pos if p >= t)
        surfaced = sum(1 for n in neg if n >= t)
        points.append({
            "threshold": t,
            "recall": kept / len(pos) if pos else float("nan"),
            "precision": kept / (kept + surfaced) if kept + surfaced else float("nan"),
            "reviews": kept + surfaced,
        })
    return points


# Bands below the bar, widest-to-narrowest gap from it. A duplicate the bar
# missed is far likelier to sit just under it than at 0.05, so the sample is
# stratified rather than uniform: with ~250 nodes there are ~31,000 pairs and a
# handful of duplicates at most, and a uniform draw of twenty finds one about
# once in three hundred tries. Stratifying puts the effort where the answer is,
# and reporting each band's population is what lets the counts be reweighted
# into an estimate for the whole population rather than just described.
BANDS = ((0.35, LOW_THRESHOLD), (0.25, 0.35), (0.15, 0.25), (-1.0, 0.15))

# Guard on an O(n^2) scan. Every pair of nodes in a scope is compared, which is
# right at this size and is not a strategy for a store a hundred times larger;
# past this the command says so rather than hanging.
MAX_NODES_FOR_FULL_SCAN = 2000


def pairs_below_bar(conn, group_ids: list[str]) -> list[tuple[str, str, float]]:
    """Every same-scope pair scoring below the review bar, with its score.

    In SQL against pgvector rather than in Python: it is the same inner product
    the candidate query uses, and the whole point is that these numbers are the
    ones the resolver would have produced.
    """
    rows = conn.execute(
        """SELECT a.node_id::text, b.node_id::text, -(b.embedding <#> a.embedding)
             FROM public.node_embedding a
             JOIN public.node_embedding b
               ON b.group_id = a.group_id AND a.node_id::text < b.node_id::text
            WHERE a.group_id = ANY(%s) AND -(b.embedding <#> a.embedding) < %s""",
        (group_ids, LOW_THRESHOLD),
    ).fetchall()
    return [(a, b, float(sim)) for a, b, sim in rows]


def sample_below(conn, group_ids: list[str], names, n: int, seed: int = SEED) -> dict:
    """A stratified random sample of pairs the bar never showed anyone.

    The one measurement this store cannot otherwise make. Every pair anyone has
    judged was above the bar by construction, so the labelled data describes the
    queue and says nothing about what never reached it. Judging a sample from
    below turns the false-negative rate from unknowable into estimable.

    Random within each band, deliberately. Picking the interesting-looking ones
    re-creates exactly the selection this exists to escape.
    """
    (count,) = conn.execute(
        "SELECT count(*) FROM public.node_embedding WHERE group_id = ANY(%s)", (group_ids,)
    ).fetchone()
    if count > MAX_NODES_FOR_FULL_SCAN:
        return {"too_large": count, "bands": []}

    pairs = pairs_below_bar(conn, group_ids)
    rng = random.Random(seed)
    per_band = max(1, n // len(BANDS))

    bands = []
    for low, high in BANDS:
        in_band = [p for p in pairs if low <= p[2] < high]
        drawn = rng.sample(in_band, min(per_band, len(in_band)))
        bands.append({
            "range": (low, high),
            "population": len(in_band),
            "sample": [
                {
                    "node_ids": [a, b], "similarity": sim,
                    "a": names.get(a, a), "b": names.get(b, b),
                }
                for a, b, sim in sorted(drawn, key=lambda p: -p[2])
            ],
        })
    return {"too_large": 0, "bands": bands, "total_pairs": len(pairs)}


def build_report(conn, config, embedder, sample: int = 0) -> dict:
    group_ids = [config.group_id(scope) for scope in ("solo", "shared")]
    embeddings = _embeddings(conn, group_ids)
    names = _names(conn, group_ids)

    neg = negatives(conn, group_ids, embeddings, names)
    pos = positives(conn, group_ids, embedder)
    p = [x["similarity"] for x in pos]
    n = [x["similarity"] for x in neg]

    return {
        "n_positives": len(p),
        "n_negatives": len(n),
        "positives": sorted(pos, key=lambda x: x["similarity"]),
        "negatives_hardest": sorted(neg, key=lambda x: -x["similarity"])[:10],
        "auc": auc(p, n),
        "auc_ci": auc_interval(p, n),
        "overlap": (
            (max(min(p), min(n)), min(max(p), max(n))) if p and n else (float("nan"),) * 2
        ),
        "operating_points": operating_points(p, n),
        "below_bar": sample_below(conn, group_ids, names, sample) if sample else None,
    }


def render(report: dict) -> str:
    lines = ["Echo Memory - threshold calibration from this store's own judgements", ""]
    if not report["n_positives"] or not report["n_negatives"]:
        lines.append(
            f"  Not enough labelled pairs: {report['n_positives']} confirmed same, "
            f"{report['n_negatives']} confirmed distinct. Judge pairs with "
            "`echo-memory trial check` first."
        )
        return "\n".join(lines) + "\n"

    lo, hi = report["auc_ci"]
    lines += [
        f"  {report['n_positives']} confirmed same, {report['n_negatives']} confirmed distinct",
        f"  AUC {report['auc']:.3f}   95% CI [{lo:.3f}, {hi:.3f}]",
    ]
    if lo <= 0.5 <= hi:
        lines.append(
            "  ! the interval includes 0.5, so on this data name similarity is not "
            "demonstrably better than a coin at this job"
        )
    if report["n_positives"] < FEW_POSITIVES:
        lines.append(
            f"  ! {report['n_positives']} positives is too few to tune a threshold on; "
            "the interval above is most of what this says"
        )
    a, b = report["overlap"]
    lines += [
        f"  the two classes overlap on [{a:.3f}, {b:.3f}]",
        "",
        f"  {'threshold':>10} {'recall':>8} {'precision':>10} {'reviews':>9}",
    ]
    for point in report["operating_points"]:
        lines.append(
            f"  {point['threshold']:>10.2f} {point['recall']:>8.0%} "
            f"{point['precision']:>10.1%} {point['reviews']:>9d}"
        )
    lines += [
        "",
        (
            f"  In use: LOW_THRESHOLD {LOW_THRESHOLD} (offer for review), "
            f"HIGH_THRESHOLD {HIGH_THRESHOLD} (merge without asking)."
        ),
        "",
        "  Every judged pair was offered for review, and a pair is only offered when",
        "  it already scores above LOW_THRESHOLD. So 'recall' above is over confirmed",
        "  duplicates that were surfaced, and says nothing about duplicates sitting",
        "  below the bar that nobody was ever shown. That number is not in this data",
        "  and no re-analysis will find it - judge a random sample from below the bar:",
        "    echo-memory calibrate --sample-below 20",
    ]

    below = report["below_bar"]
    if below and below.get("too_large"):
        lines += [
            "",
            (
                f"  {below['too_large']} nodes is past the "
                f"{MAX_NODES_FOR_FULL_SCAN}-node limit for the below-bar scan, "
                "which compares every pair."
            ),
        ]
    elif below and below.get("bands"):
        lines += [
            "",
            f"  {below['total_pairs']} pair(s) sit below the bar and have never been shown to",
            "  anyone. A stratified sample, so judging a handful estimates the rest - the",
            "  population of each band is what lets these counts be reweighted:",
        ]
        for band in below["bands"]:
            low, high = band["range"]
            floor = "below" if low < 0 else f"{low:.2f} to"
            lines += ["", f"  [{floor} {high:.2f}]  {band['population']} pair(s) in this band"]
            for pair in band["sample"]:
                lines.append(f"    {pair['similarity']:.3f}  {pair['a']!r}  vs  {pair['b']!r}")
                lines.append(
                    f"           echo-memory trial dup|not-dup {pair['node_ids'][0]} "
                    f"{pair['node_ids'][1]} \"...\""
                )
    return "\n".join(lines) + "\n"


def run(args, config, conn) -> int:
    from echo_memory.ingestion.embeddings import LocalEmbedder

    print(render(build_report(conn, config, LocalEmbedder(), sample=args.sample_below or 0)), end="")
    return 0
