# Deferred

Not urgent, not forgotten. See `docs/designs/echo-memory-design.md` for the
active build plan; this is for real deferrals with a stated reason, not a
backlog dump.

- **CI doesn't run the integration test suite against a real database.**
  `tests/integration/` (migration correctness, graph/audit/embedding
  round-trip) self-skips when `ECHO_MEMORY_DATABASE_URL` is unreachable,
  which is always true in CI right now: GitHub Actions' `services:` can only
  pull a pre-built image, and our Postgres+AGE+pgvector image is built from
  source (see `docker/postgres.Dockerfile`, and PR0a's spike notes on why).
  CI currently only exercises unit tests. Fix: either publish the built image
  to a registry CI can pull, or add a build-the-image step before the test
  job. Priority: P2, before the PR2/PR3 lanes land real ingestion/retrieval
  logic that most needs this coverage.
- **Slack/email delivery for contradiction notifications** (v1b,
  `contradicts` surfacing). A local notification/log mechanism is in v1b
  scope already (see the CEO plan); only external delivery channels with
  real credentials/rate-limiting infra remain deferred. Depends on: local
  notification shipping and proving insufficient on its own. Priority: P3.
- **Full CI/CD publish pipeline** (GitHub Releases or a package registry,
  versioned builds). Needed before external adopters can install without
  cloning and building manually. Depends on: v1a exit criteria met, embedding
  provider and license questions resolved. Priority: P3.
