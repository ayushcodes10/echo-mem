# Deferred

Not urgent, not forgotten. See `docs/designs/echo-memory-design.md` for the
active build plan; this is for real deferrals with a stated reason, not a
backlog dump.

- **Slack/email delivery for contradiction notifications** (v1b,
  `contradicts` surfacing). A local notification/log mechanism is in v1b
  scope already (see the CEO plan); only external delivery channels with
  real credentials/rate-limiting infra remain deferred. Depends on: local
  notification shipping and proving insufficient on its own. Priority: P3.
- **`SessionEnd` capture hook.** `PreCompact` now fires a reminder before
  context is summarised away, and `PostToolUse` queues memory files as they're
  written. `SessionEnd` would catch what a session learned but never wrote down
  at all. Deferred because it overlaps `PostToolUse`'s coverage and adds a
  second thing that can fire noisily at a bad moment. Depends on: `PreCompact`
  shipping and proving insufficient on its own. Priority: P3.
- **Full CI/CD publish pipeline** (GitHub Releases or a package registry,
  versioned builds). Needed before external adopters can install without
  cloning and building manually. Depends on: v1a exit criteria met, embedding
  provider and license questions resolved. Priority: P3.
