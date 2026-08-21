"""get_audit_log: read-only access to the append-only audit trail (see the
design doc's Concrete Schema "Audit log table" section). Entries are
returned chronologically (oldest first): since `since` is a lower bound
moving forward in time, that's the natural reading order for a trail of
what happened, not a "most recent first" feed."""

import time
from datetime import UTC, datetime

from echo_memory.infra.logging import get_logger

MAX_ENTRIES = 500

_logger = get_logger("get_audit_log")


class ValidationError(Exception):
    pass


def _parse_since(since: str | None) -> datetime | None:
    if since is None:
        return None
    try:
        dt = datetime.fromisoformat(since)
    except ValueError as e:
        raise ValidationError(f"invalid since timestamp: {since!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def get_audit_log(conn, group_id: str, since: str | None = None) -> dict:
    start = time.perf_counter()
    try:
        since_dt = _parse_since(since)
    except ValidationError as e:
        _logger.info(
            "get_audit_log",
            extra={"fields": {"group_id": group_id, "error": str(e)}},
        )
        return {"error": str(e)}

    rows = conn.execute(
        """
        SELECT "timestamp", mutation_type, affected_edge_ids::text[],
               affected_node_id::text, before_fact, after_fact, session_id,
               summary, resolution_detail
        FROM public.audit_entry
        WHERE group_id = %s
          AND (%s::timestamptz IS NULL OR "timestamp" >= %s::timestamptz)
        ORDER BY "timestamp" ASC
        LIMIT %s
        """,
        (group_id, since_dt, since_dt, MAX_ENTRIES),
    ).fetchall()

    entries = [
        {
            "timestamp": ts.isoformat(),
            "mutation_type": mutation_type,
            "affected_edge_ids": affected_edge_ids or [],
            "affected_node_id": affected_node_id,
            "before_fact": before_fact,
            "after_fact": after_fact,
            "session_id": session_id,
            "summary": summary,
            "resolution_detail": resolution_detail,
        }
        for (
            ts,
            mutation_type,
            affected_edge_ids,
            affected_node_id,
            before_fact,
            after_fact,
            session_id,
            summary,
            resolution_detail,
        ) in rows
    ]

    _logger.info(
        "get_audit_log",
        extra={
            "fields": {
                "group_id": group_id,
                "n_entries": len(entries),
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            }
        },
    )
    return {"entries": entries}
