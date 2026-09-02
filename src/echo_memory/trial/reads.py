"""How often memory was read, and what it cost to inject.

Best-effort throughout. This is instrumentation on the hot path - the
UserPromptSubmit hook runs in a fresh process on every prompt - and a
measurement that can fail a prompt is worse than no measurement."""

from __future__ import annotations

from echo_memory.infra.logging import get_logger

_logger = get_logger("read_event")

HOOK = "hook"
QUERY = "query_memory"

# The ratio characters-to-tokens for English prose. Rough on purpose: the point
# is an order of magnitude a reader can act on, not a billing figure, and the
# real number depends on a tokenizer this server deliberately does not carry.
CHARS_PER_TOKEN = 4


def record(
    conn,
    group_id: str,
    kind: str,
    n_facts: int,
    injected_chars: int,
    project: str | None = None,
    session_id: str | None = None,
) -> None:
    """Never raises. A prompt must reach the agent whether or not this works.

    project and session_id are optional because this runs on the prompt path
    against whatever CLI version is installed; an unattributed read is worth
    more than an exception between the user and the agent."""
    try:
        conn.execute(
            """INSERT INTO public.read_event
                   (group_id, kind, n_facts, injected_chars, project, session_id)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (group_id, kind, n_facts, injected_chars, project, session_id),
        )
    except Exception as e:  # noqa: BLE001 - see docstring: never blocks a prompt
        _logger.warning("read_event_not_recorded", extra={"error": str(e)})


def summary(conn, group_ids: list[str], days: int = 7) -> dict:
    """Reads and their cost over a window, next to the saves they produced.

    Saves come from trial_observation rather than being inferred: a read that
    helped is a judgement the agent makes, and this only counts how many times
    it made one against how many chances it had."""
    row = conn.execute(
        """SELECT count(*), coalesce(sum(injected_chars), 0),
                  count(*) FILTER (WHERE n_facts > 0)
           FROM public.read_event
           WHERE group_id = ANY(%s) AND at > now() - make_interval(days => %s)""",
        (group_ids, days),
    ).fetchone()
    reads, chars, with_facts = (row or (0, 0, 0))
    saves = conn.execute(
        """SELECT count(*) FROM public.trial_observation
           WHERE group_id = ANY(%s) AND kind = 'recall_save'
             AND timestamp > now() - make_interval(days => %s)""",
        (group_ids, days),
    ).fetchone()
    return {
        "days": days,
        "reads": reads or 0,
        "reads_with_facts": with_facts or 0,
        "injected_chars": chars or 0,
        "injected_tokens": (chars or 0) // CHARS_PER_TOKEN,
        "saves": (saves or [0])[0],
    }


def by_project(conn, group_ids: list[str], days: int = 7) -> list[dict]:
    """Reads per project, so the cost of recall can be read against the repo
    that paid it. This is the question read_event could not answer on the day
    it shipped: every row carried the same group_id, so 12 reads across four
    repos and 12 reads in one were indistinguishable."""
    rows = conn.execute(
        """SELECT coalesce(project, 'unattributed'), count(*),
                  count(*) FILTER (WHERE n_facts > 0),
                  coalesce(sum(injected_chars), 0),
                  count(DISTINCT session_id)
           FROM public.read_event
           WHERE group_id = ANY(%s) AND at > now() - make_interval(days => %s)
           GROUP BY 1 ORDER BY 2 DESC""",
        (group_ids, days),
    ).fetchall()
    return [
        {
            "project": r[0],
            "reads": r[1],
            "reads_with_facts": r[2],
            "injected_chars": r[3],
            "injected_tokens": r[3] // CHARS_PER_TOKEN,
            "sessions": r[4],
        }
        for r in rows
    ]
