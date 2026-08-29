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

from echo_memory.retrieval.query_memory import query_memory

# Injected on every prompt, so this stays small. Three facts is enough to
# answer "we already know this" without crowding out the user's actual words.
DEFAULT_TOP_K = 3
FACT_PREVIEW_CHARS = 220

# Below this many characters a prompt is "yes", "go on", "fix it" - words that
# match everything lexically and mean nothing. Retrieving against them returns
# noise dressed as relevance.
MIN_PROMPT_CHARS = 12


def recall_for_prompt(conn, config, prompt: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """Facts worth showing for this prompt, across both scopes."""
    prompt = (prompt or "").strip()
    if len(prompt) < MIN_PROMPT_CHARS:
        return {"prompt": prompt, "skipped": "prompt too short to retrieve against",
                "facts": []}

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
    return {"prompt": prompt, "skipped": None, "facts": unique[:top_k]}


def render_context(result: dict) -> str:
    """Empty string means inject nothing. Callers must treat that as 'stay
    quiet', not as an error."""
    if not result["facts"]:
        return ""
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
    return "\n".join(lines)


def render_hook_output(context: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }
    )
