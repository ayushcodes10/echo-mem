"""echo-memory recall: retrieval for the UserPromptSubmit hook.

Every other surface asks the agent to remember to call `query_memory`. The
dugout transcript on 2026-08-25 showed what that is worth: the session-start
briefing landed in context, the agent then made 31 tool calls, and not one of
them was a memory call. The plumbing was fine; remembering was the problem.

`UserPromptSubmit` is the one hook that fires on every prompt and knows what
was asked, so memory can be retrieved *against the prompt* and injected before
the agent does anything. No decision to forget.

Two constraints shape this:

**No embedding model.** The hook runs in a fresh process per prompt and the
embedder costs 6.2 seconds of cold start (measured, see cli/benchmark.py).
So retrieval here is lexical-only - Postgres full-text search, no model.
Recall is genuinely worse than a full query_memory call, and that is the
correct trade: some relevant memory arriving on every prompt beats better
memory arriving when somebody remembers to ask.

**Silence when there is nothing to say.** This injects into every prompt the
user types. A hook that always speaks becomes noise the model learns to skim,
which is how the session briefing lost to three competing hooks. Below a
relevance floor it emits nothing at all."""

import json
from datetime import UTC, datetime

from echo_memory.ingestion import capture
from echo_memory.retrieval.query_memory import query_memory

# Injected on every prompt, so this stays small. Three facts is enough to
# answer "we already know this" without crowding out the user's actual words.
DEFAULT_TOP_K = 3
FACT_PREVIEW_CHARS = 220

# Below this many characters a prompt is "yes", "go on", "fix it" - words that
# match everything lexically and mean nothing. Retrieving against them returns
# noise dressed as relevance.
MIN_PROMPT_CHARS = 12

# Days without a write before the hook says so. Three is long enough that a
# quiet weekend does not trigger it and short enough that a habit which has
# stopped is caught in the same week rather than at the trial's end.
QUIET_DAYS = 3


def unwritten_work(conn, config) -> dict:
    """What this session has queued but not recorded, and whether it has
    recorded anything at all.

    Both signals existed and neither reached the agent. `pending_ingest` is
    populated by the PostToolUse hook and the nudge to drain it lived inside
    `query_memory`'s response (server.py:157) - so an agent learned work was
    queued only by calling a tool it does not spontaneously call, which is the
    exact reason this hook exists. And nothing anywhere said "you have written
    nothing today".

    Measured, not theorised: across 2026-08-28 to 08-31 an agent did eight
    merged PRs on this repository and called write_episode zero times, while
    three noticed files sat unprocessed."""
    queued = capture.pending(conn)
    row = conn.execute(
        """SELECT max(timestamp) FROM public.audit_entry
           WHERE mutation_type = 'created' AND group_id = ANY(%s)""",
        ([config.group_id(s) for s in ("solo", "shared")],),
    ).fetchone()
    last = row[0] if row and row[0] else None
    days = (datetime.now(UTC) - last).days if last else None
    return {"pending": len(queued), "days_since_write": days}


def recall_for_prompt(conn, config, prompt: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """Facts worth showing for this prompt, across both scopes."""
    prompt = (prompt or "").strip()
    if len(prompt) < MIN_PROMPT_CHARS:
        return {
            "prompt": prompt, "skipped": "prompt too short to retrieve against",
            "facts": [], **unwritten_work(conn, config),
        }

    facts = []
    for scope in ("shared", "solo"):
        result = query_memory(
            conn, config.group_id(scope), prompt, top_k, embedder=None, lexical_only=True
        )
        if "error" in result:
            return {"prompt": prompt, "skipped": result["error"], "facts": []}
        for fact in result["facts"]:
            fact["scope"] = scope
            facts.append(fact)

    seen, unique = set(), []
    for fact in facts:
        if fact["fact"] in seen:
            continue
        seen.add(fact["fact"])
        unique.append(fact)
    return {
        "prompt": prompt, "skipped": None, "facts": unique[:top_k],
        **unwritten_work(conn, config),
    }


def render_context(result: dict) -> str:
    """Empty string means inject nothing. Callers must treat that as 'stay
    quiet', not as an error."""
    write_side = _write_side_lines(result)
    if not result["facts"]:
        # Silence is the default, but a store nobody is writing to is worth
        # saying out loud even when nothing matched the prompt. Both conditions
        # here are self-limiting: writing clears them.
        return "\n".join(write_side) + "\n" if write_side else ""
    lines = [
        (
            "Echo Memory already knows this, retrieved for the prompt above. "
            "Use it instead of re-deriving or asking the user again:"
        )
    ]
    for fact in result["facts"]:
        text = fact["fact"]
        if len(text) > FACT_PREVIEW_CHARS:
            text = text[:FACT_PREVIEW_CHARS].rstrip() + "..."
        # Attribution has to travel with the fact. This hook fires on every
        # prompt and is where a save becomes recognisable at all, yet it used to
        # emit bare text while instructing the agent to report who wrote it -
        # asking for a value the payload never carried.
        prov = fact.get("provenance") or {}
        author, fact_id = prov.get("agent_id"), fact.get("fact_id")
        tag = f" [written by {author}, fact_id {fact_id}]" if author and fact_id else ""
        lines.append(f"- {text}{tag}")
    lines.append(
        "If one of these saved the user re-explaining something a different tool told "
        "them, call record_recall_save with that fact's fact_id. Call query_memory for "
        "the fuller picture - this is a keyword match, not a semantic one."
    )
    lines += write_side
    return "\n".join(lines)


def _write_side_lines(result: dict) -> list[str]:
    """The write half. Reads were made automatic by this hook; writes stayed a
    polite request in a tool description, and the observed write rate was zero.

    Deliberately terse and deliberately conditional. This fires on every prompt,
    and a hook that always speaks becomes noise the model learns to skim - the
    failure that lost the session briefing to three competing hooks."""
    lines = []
    queued = result.get("pending") or 0
    days = result.get("days_since_write")
    if queued:
        lines.append(
            f"{queued} memory file(s) noticed but not in the graph yet. Run "
            "`echo-memory pending` to see them, read them, and write_episode what "
            "matters; then `echo-memory pending --done <path>`."
        )
    if days is not None and days >= QUIET_DAYS:
        lines.append(
            f"Nothing has been written to memory in {days} days. If this session has "
            "produced a decision, a correction, or a hard-won finding, call "
            "write_episode now rather than at the end."
        )
    return lines


def render_hook_output(context: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }
    )
