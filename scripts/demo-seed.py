#!/usr/bin/env python3
"""Seed a throwaway store with a synthetic graph, for documentation images.

The real store is not usable for screenshots: it holds live infrastructure
detail - account numbers, hostnames, internal IPs - and this repo is public.
It is also a poor example, because one person's memory is idiosyncratic where
a README wants something legible.

So this builds a small believable graph instead: three projects, a few
genuinely-connected ideas inside each, and one entity referenced from two of
them, which is what makes clustering worth looking at.

    ECHO_MEMORY_DATABASE_URL=postgresql://.../echo_memory_demo \\
    ECHO_MEMORY_USER_ID=demo ECHO_MEMORY_AGENT_ID=claude-code \\
        python scripts/demo-seed.py

Point it at a scratch database. It writes real facts through the real code
path, so anything it touches is indistinguishable from ordinary memory.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from echo_memory import server
from echo_memory.infra.config import Config

EPISODES = [
    ("checkout-api", "sess-checkout-1", [
        {"name": "checkout-api", "type": "service"},
        {"name": "Stripe webhooks", "type": "integration"},
        {"name": "idempotency keys", "type": "pattern"},
    ], [
        {"source": "checkout-api", "target": "Stripe webhooks", "relation_type": "receives",
         "fact": "checkout-api receives Stripe webhooks at POST /hooks/stripe. Stripe retries "
                "for up to 3 days on any non-2xx, so the handler must ack fast and do work "
                "asynchronously.", "confidence": "extracted"},
        {"source": "Stripe webhooks", "target": "idempotency keys", "relation_type": "requires",
         "fact": "Stripe can deliver the same webhook more than once, so every handler is keyed "
                 "on the event id. Two duplicate deliveries in March double-charged four "
                 "customers before this was added.", "confidence": "extracted"},
    ]),
    ("checkout-api", "sess-checkout-2", [
        {"name": "checkout-api", "type": "service"},
        {"name": "refund flow", "type": "feature"},
        {"name": "idempotency keys", "type": "pattern"},
    ], [
        {"source": "refund flow", "target": "checkout-api", "relation_type": "lives_in",
         "fact": "Refunds are issued from checkout-api rather than the admin panel, because the "
                 "ledger write and the Stripe call have to happen in one transaction.",
         "confidence": "extracted"},
        {"source": "refund flow", "target": "idempotency keys", "relation_type": "requires",
         "fact": "A refund retried after a timeout must reuse the original idempotency key, or "
                 "Stripe treats it as a second refund.", "confidence": "extracted"},
    ]),
    ("checkout-api", "sess-checkout-3", [
        {"name": "checkout-api", "type": "service"},
        {"name": "staging deploys from main", "type": "policy"},
        {"name": "release checklist", "type": "process"},
    ], [
        {"source": "checkout-api", "target": "staging deploys from main", "relation_type": "governed_by",
         "fact": "checkout-api deploys to staging from main and to production from a release tag. "
                 "Never merge staging into main; the branches have diverged since the payments "
                 "rewrite.", "confidence": "extracted"},
        {"source": "release checklist", "target": "staging deploys from main", "relation_type": "enforces",
         "fact": "The release checklist requires a staging soak of at least one full billing cycle "
                 "before tagging, because the nightly invoice job is the usual thing to break.",
         "confidence": "extracted"},
    ]),
    ("mobile-app", "sess-mobile-1", [
        {"name": "mobile-app", "type": "app"},
        {"name": "offline queue", "type": "component"},
        {"name": "idempotency keys", "type": "pattern"},
    ], [
        {"source": "mobile-app", "target": "offline queue", "relation_type": "uses",
         "fact": "mobile-app queues writes locally when offline and replays them on reconnect, "
                 "which means the server sees bursts of stale-but-valid requests after a tunnel.",
         "confidence": "extracted"},
        {"source": "offline queue", "target": "idempotency keys", "relation_type": "depends_on",
         "fact": "The offline queue replays with the original idempotency key, so a request sent "
                 "twice from two devices resolves to one write. This is why the key is generated "
                 "on the client, not the server.", "confidence": "extracted"},
    ]),
    ("mobile-app", "sess-mobile-2", [
        {"name": "mobile-app", "type": "app"},
        {"name": "push token rotation", "type": "gotcha"},
        {"name": "notification service", "type": "service"},
    ], [
        {"source": "push token rotation", "target": "mobile-app", "relation_type": "gotcha_in",
         "fact": "iOS rotates the push token silently after a restore from backup. Tokens must be "
                 "re-registered on every launch, not only on first install, or a restored device "
                 "stops receiving notifications with no error anywhere.", "confidence": "extracted"},
        {"source": "notification service", "target": "push token rotation", "relation_type": "affected_by",
         "fact": "notification service prunes tokens APNs reports as invalid, which is the only "
                 "signal that a rotation was missed.", "confidence": "extracted"},
    ]),
    ("data-pipeline", "sess-pipeline-1", [
        {"name": "data-pipeline", "type": "service"},
        {"name": "nightly rollup", "type": "job"},
        {"name": "timezone bug", "type": "bug"},
    ], [
        {"source": "data-pipeline", "target": "nightly rollup", "relation_type": "runs",
         "fact": "data-pipeline runs the nightly rollup at 02:00 UTC. It is not timezone-aware, "
                 "so figures for the previous day are only final after 02:00 UTC, not at local "
                 "midnight.", "confidence": "extracted"},
        {"source": "timezone bug", "target": "nightly rollup", "relation_type": "found_in",
         "fact": "The rollup double-counted the hour after a DST change for two years, because it "
                 "bucketed on local time and summed on UTC. Fixed by bucketing on UTC throughout.",
         "confidence": "extracted"},
    ]),
    ("data-pipeline", "sess-pipeline-2", [
        {"name": "data-pipeline", "type": "service"},
        {"name": "backfill runbook", "type": "process"},
        {"name": "nightly rollup", "type": "job"},
    ], [
        {"source": "backfill runbook", "target": "nightly rollup", "relation_type": "repairs",
         "fact": "A backfill re-runs the rollup for a date range with the scheduler paused. "
                 "Running it while the scheduler is live produces duplicate rows that the unique "
                 "index does not catch, because the partition key includes the run id.",
         "confidence": "extracted"},
    ]),
]


def main() -> int:
    config = Config(
        user_id=os.environ.get("ECHO_MEMORY_USER_ID", "demo"),
        agent_id=os.environ.get("ECHO_MEMORY_AGENT_ID", "claude-code"),
        database_url=os.environ["ECHO_MEMORY_DATABASE_URL"],
    )
    written = 0
    for project, session_id, entities, facts in EPISODES:
        server.startup(config=Config(config.user_id, config.agent_id, config.database_url, project))
        result = server.write_episode("shared", session_id, entities, facts)
        if result.get("error"):
            print(f"  {project}: {result['error']}")
            return 1
        written += len(result.get("edges_created", []))
        print(f"  {project:<14} {session_id:<20} +{len(result.get('edges_created', []))} facts")
    print(f"\n{written} facts written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
