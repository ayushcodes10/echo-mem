"""Seed a demo store dense enough to be worth a screenshot.

The landing page showed a dashboard holding fourteen nodes, which argues
against the product: a memory layer whose picture fits in a corner of the frame
has not been used. The real store this was built in has hundreds, and cannot be
shown - it carries AWS account ids, client hostnames and a tax registration.

So this invents a plausible engineering organisation instead. Nothing here is
real, and nothing real is copied into it. What it does reproduce faithfully is
the *shape* of a store that has been used for months: a handful of services,
each with its own vocabulary, and a thin seam of concepts that turn up in more
than one of them. That seam is the whole argument of the page - clusters are a
property of the edges, and nobody drew them.

Facts are written through write_episode rather than inserted, so everything the
dashboard reads is real: provenance, entity resolution, the audit trail,
agent attribution, the embeddings retrieval uses. A store assembled by INSERT
would render the same picture and prove nothing about the code that draws it.
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from echo_memory.infra.db import connect
from echo_memory.ingestion.embeddings import LocalEmbedder
from echo_memory.ingestion.write_episode import write_episode

SEED = 11
GROUP = "user:demo:shared"

# Each service gets its own nouns, because a store where every project talks
# about the same things has no clusters to find.
SERVICES: dict[str, list[str]] = {
    "checkout-api": [
        "refund flow", "idempotency keys", "Stripe webhooks", "payment gateway",
        "retry policy", "3DS challenge", "settlement batch", "dispute handler",
        "currency rounding", "invoice numbering", "checkout session", "tax engine",
    ],
    "mobile-app": [
        "offline queue", "push token rotation", "deep links", "idempotency keys",
        "biometric unlock", "image cache", "cold start budget", "release checklist",
        "crash symbolication", "feature flags", "background refresh",
    ],
    "data-pipeline": [
        "nightly rollup", "backfill runbook", "timezone bug", "watermark table",
        "late arrivals", "partition pruning", "schema registry", "dead letter topic",
        "column lineage", "compaction job",
    ],
    "auth-service": [
        "session cookie", "refresh rotation", "device fingerprint", "rate limiter",
        "password reset", "OAuth callback", "token revocation", "audit log",
        "feature flags", "MFA enrolment",
    ],
    "search-service": [
        "index rebuild", "synonym list", "query planner", "relevance eval",
        "shard rebalance", "typo tolerance", "embedding drift", "stopword list",
        "facet counts",
    ],
    "platform": [
        "deploy pipeline", "blue-green cutover", "secret rotation", "log retention",
        "on-call rota", "cost dashboard", "terraform modules", "staging parity",
        "release checklist", "rate limiter", "audit log",
    ],
}

# The seam. Each of these is written about by more than one service, which is
# what pulls otherwise separate clusters into one graph.
SHARED = ["idempotency keys", "feature flags", "release checklist", "rate limiter", "audit log"]

RELATIONS = [
    "caused_by", "led_to", "blocked_by", "depends_on", "verified_by",
    "supersedes", "constrains", "measured_by", "owned_by",
]

TEMPLATES = [
    "{a} broke because {b} was assumed idempotent and is not.",
    "{a} has to run before {b}, or the second one reads a half-written table.",
    "The incident on the 14th traced to {a}: {b} retried without a key.",
    "{a} is the only consumer of {b} left, so changing it is cheaper than it looks.",
    "Do not touch {a} without re-running {b} - it is the only thing that catches the regression.",
    "{a} was measured at four times the cost of {b} and is the next thing to cut.",
    "{b} owns {a} now; the previous team's runbook is out of date.",
    "{a} silently falls back to {b} when the cache is cold, which hid the bug for a week.",
    "After the migration, {a} and {b} disagree about timezone handling.",
    "{a} is rate limited by {b}, not by the database, which is where everyone looks first.",
]

AGENTS = ["claude-code", "cursor", "codex", "claude-desktop"]


def episodes(rng: random.Random) -> list[dict]:
    out: list[dict] = []
    for service, terms in SERVICES.items():
        pairs = list(itertools.combinations(terms, 2))
        rng.shuffle(pairs)
        # Enough edges to look worked-in, few enough that the layout still has
        # air in it. A hairball is as uninformative as fourteen nodes.
        for i, (a, b) in enumerate(pairs[: int(len(terms) * 1.7)]):
            out.append({
                "project": service,
                "session": f"{service}-{i // 4}",
                "agent": rng.choice(AGENTS),
                "source": a,
                "target": b,
                "relation": rng.choice(RELATIONS),
                "fact": rng.choice(TEMPLATES).format(a=a, b=b),
            })

    # Cross-service facts: the reason the clusters are joined at all.
    services = list(SERVICES)
    for concept in SHARED:
        owners = [s for s, t in SERVICES.items() if concept in t]
        for service in owners:
            other = rng.choice([s for s in services if s != service])
            partner = rng.choice(SERVICES[other])
            out.append({
                "project": service,
                "session": f"{service}-shared",
                "agent": rng.choice(AGENTS),
                "source": concept,
                "target": partner,
                "relation": rng.choice(RELATIONS),
                "fact": rng.choice(TEMPLATES).format(a=concept, b=partner),
            })
    rng.shuffle(out)
    return out


def main(database_url: str) -> None:
    rng = random.Random(SEED)
    embedder = LocalEmbedder()
    embedder.warm()
    plan = episodes(rng)

    written = failed = 0
    with connect(database_url) as conn:
        for e in plan:
            names = list(dict.fromkeys([e["source"], e["target"]]))
            result = write_episode(
                conn, GROUP, e["session"],
                [{"name": n, "type": "concept"} for n in names],
                [{
                    "source": e["source"], "target": e["target"],
                    "relation_type": e["relation"], "fact": e["fact"],
                    "confidence": "extracted",
                }],
                # Deliberately no entity_resolutions on the first attempt: let
                # the resolver decide, so the audit trail the dashboard renders
                # is one it actually produced.
                None, embedder, project=e["project"], agent_id=e["agent"],
            )
            if result.get("ambiguous_entities"):
                # The resolver asked. Answering "new" is safe rather than lazy:
                # an exact name match overrides the claim, so a genuine repeat
                # still lands on the existing node - only a genuinely near-miss
                # name gets its own. Without this the demo store loses a fifth
                # of its facts to unanswered questions.
                result = write_episode(
                    conn, GROUP, e["session"],
                    [{"name": n, "type": "concept"} for n in names],
                    [{
                        "source": e["source"], "target": e["target"],
                        "relation_type": e["relation"], "fact": e["fact"],
                        "confidence": "extracted",
                    }],
                    {n: {"resolved_to": "new"} for n in names},
                    embedder, project=e["project"], agent_id=e["agent"],
                )
            if result.get("edges_created"):
                written += 1
            else:
                failed += 1
    print(f"wrote {written} facts, {failed} deferred or refused")


if __name__ == "__main__":
    main(sys.argv[1])
