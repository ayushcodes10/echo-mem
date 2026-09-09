"""How much a session did, and whether it recorded any of it.

The Stop gate could already see memory files a session wrote and failed to
ingest. It could not see the larger case: a session that did a great deal and
wrote no memory file at all, which reads as nothing owed because the queue is
empty.

Two numbers close that. `n_edits` comes from the PostToolUse hook, which
already fires on every Write and Edit and until now discarded everything that
was not a memory file. Facts written come from the audit log, which has
recorded a session_id per fact since the beginning. Neither is new
instrumentation; the pairing is.

Counts only, deliberately. No paths, no diffs, no file names - the same line
migration 0008 drew for reads. A number per session is enough to ask "did this
session work without recording anything" and not enough to reconstruct what it
worked on.
"""

from __future__ import annotations

import logging

_logger = logging.getLogger("echo_memory.activity")

# Edits below which a session is not worth interrupting. A one or two file
# session is a typo fix or a rename, and the MCP tool description already tells
# agents to skip those - a gate that fires on them teaches people to disable it,
# which is how the SessionStart briefing lost.
MIN_EDITS_TO_ASK = 5


def record_edit(conn, session_id: str, project: str) -> None:
    """One edit happened. Never raises: this runs on the PostToolUse path and a
    memory side effect has no business failing the edit that triggered it."""
    if not session_id or not project:
        return
    try:
        conn.execute(
            """INSERT INTO public.session_activity (session_id, project, n_edits)
               VALUES (%s, %s, 1)
               ON CONFLICT (session_id) DO UPDATE
                   SET n_edits = session_activity.n_edits + 1, last_at = now()""",
            (session_id, project),
        )
    except Exception:  # noqa: BLE001 - see docstring
        _logger.warning("session_activity_not_recorded", extra={"session": session_id})


def edits_by(conn, session_id: str) -> int:
    if not session_id:
        return 0
    row = conn.execute(
        "SELECT n_edits FROM public.session_activity WHERE session_id = %s", (session_id,)
    ).fetchone()
    return int(row[0]) if row else 0


def facts_written_by(conn, session_id: str) -> int:
    """From the audit log rather than a counter, so it cannot drift from what
    is actually in the graph."""
    if not session_id:
        return 0
    row = conn.execute(
        """SELECT count(*) FROM public.audit_entry
           WHERE session_id = %s AND mutation_type = 'created'""",
        (session_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def worked_without_recording(conn, session_id: str, min_edits: int = MIN_EDITS_TO_ASK) -> dict:
    """Did this session do substantial work and record none of it?

    Returns the numbers as well as the verdict, because the gate has to be able
    to say "you changed 14 files and wrote nothing" rather than assert that
    something is missing. A claim with the count attached is checkable by the
    agent reading it; one without is just nagging.
    """
    edits = edits_by(conn, session_id)
    facts = facts_written_by(conn, session_id)
    return {
        "edits": edits,
        "facts": facts,
        "should_ask": edits >= min_edits and facts == 0,
    }
