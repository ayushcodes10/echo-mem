# What echo-mem is, in CoALA's vocabulary

CoALA (Sumers et al., *Cognitive Architectures for Language Agents*) gives the
agent-memory field its standard four-way split, and most of the 2026 writing on
the subject adds a fifth layer for forgetting. It is worth mapping this system
onto that vocabulary for one reason: it says precisely what was built and what
was not, in terms a reader already holds, without claiming either.

| CoALA layer | echo-mem | where |
|---|---|---|
| **working** (the context window) | none, by design | the host agent owns it |
| **episodic** (what happened) | the audit log | `audit_entry`, `read_event` |
| **semantic** (what is true) | the fact graph | AGE `FACT` edges |
| **procedural** (how to do things) | **none** | — |
| **forgetting** (what to drop) | **none**, and now measured | `trial/reads.unreturned` |

## Episodic is the part nobody talks about

The audit log was built for provenance - every creation, resolution and
supersession carries the before and after text, the session, the agent and the
package version that wrote it. In CoALA's terms that is episodic memory, and it
is the layer most systems in this category do not have at all. It is what makes
a claim like "this fact came from Codex on the 12th and superseded one written
by Claude Code on the 3rd" checkable rather than asserted.

It is not offered to the agent as a retrieval surface, which is a gap rather
than a decision. `get_audit_log` exists as an MCP tool; nothing retrieves
against it.

## Procedural memory is absent and out of scope

Storing "how to do things" is a different product with a different failure
mode: a stale skill is worse than a forgotten one, because it executes. This
system stores facts about a codebase, and the honest position is that it does
not attempt the procedural layer rather than that it does it badly.

## Forgetting is absent, and that is now a number

Nothing has ever left this store. Supersession marks a fact invalid when the
same triple is rewritten, and that is the whole of it: 401 creations against a
handful of supersessions.

The literature answers this with policy - decay curves, TTLs, eviction rules -
chosen before anyone counts. `echo-memory health` now reports the count
instead: **323 of 537 active facts were returned to nobody in 30 days, 60% of
the store.**

That number proposes nothing. A fact nothing returned may be the one that
matters next week, or retrieval may be failing to reach it, and those want
opposite responses. Two limits are worth carrying with it:

- it needs `returned_fact_ids` (migration 0021), so the window cannot reach
  further back than that. A short history reads as a larger unreturned share,
  which makes this a floor rather than a measurement of decay.
- it counts active facts only. A superseded fact is not unreachable, it is
  gone.

## What this mapping is not

It is not a claim to implement CoALA, and the numbers circulating alongside
this vocabulary - "90% token reduction", "91% lower latency", "20% accuracy
from one ontology layer" - are vendor self-reports on vendor benchmarks. They
are not comparable to anything measured here and are not cited.

This project's cost claim is narrower and checkable: zero **additional**
server-side inference, by construction, with extraction moved to the calling
agent and named as such.
