"""The automatic-capture queue.

The problem this solves, measured rather than assumed: over two days of the
v1a trial, `write_episode` fired 4 times because a model chose to call it,
while the agent's own file-based memory wrote 7 files in the same window
because a hook fired deterministically. The capture path already exists and
works; it just wasn't wired here.

A hook calls `notice()` when a memory file is written. That's the
deterministic half: the queue knows something changed and can't forget it.
Extraction into entities and facts stays with the calling agent, because the
server never calls an LLM (design doc, MCP tool contract, architecture pivot).
`query_memory` surfaces the open queue at session start so the agent that can
do the extraction is told there's work.

The queue stores a digest, not the file's content: it tracks what still needs
reading, and a second copy of the memory would be one more thing to keep in
sync and one more place for the same fact to disagree with itself."""

import hashlib
from pathlib import Path


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def notice(conn, path: str, project: str, digest: str, source: str = "file") -> dict:
    """Record that a memory file needs ingesting. Re-noticing the same path
    with the same digest is a no-op (a hook can fire several times for one
    edit); a changed digest reopens it, because the file now says something
    the graph hasn't heard."""
    row = conn.execute(
        """
        INSERT INTO public.pending_ingest (path, project, digest, source)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (path) DO UPDATE
            SET project = EXCLUDED.project,
                digest = EXCLUDED.digest,
                source = EXCLUDED.source,
                noticed_at = now(),
                ingested_at = CASE
                    WHEN public.pending_ingest.digest IS DISTINCT FROM EXCLUDED.digest
                    THEN NULL ELSE public.pending_ingest.ingested_at END
            WHERE public.pending_ingest.digest IS DISTINCT FROM EXCLUDED.digest
        RETURNING path, project, digest, ingested_at
        """,
        (path, project, digest, source),
    ).fetchone()
    if row is None:
        return {"path": path, "project": project, "changed": False}
    return {"path": row[0], "project": row[1], "digest": row[2], "changed": True}


def notice_file(conn, path: str | Path, project: str, source: str = "file") -> dict:
    p = Path(path)
    return notice(conn, str(p), project, digest_of(p.read_text(errors="replace")), source)


def pending(conn, project: str | None = None) -> list[dict]:
    sql = """SELECT path, project, digest, noticed_at, source FROM public.pending_ingest
             WHERE ingested_at IS NULL"""
    params: tuple = ()
    if project:
        sql += " AND project = %s"
        params = (project,)
    # Hand-written notes before generated digests: if an agent only gets
    # through part of the queue, it should have read the densest material.
    sql += """ ORDER BY CASE source
                   WHEN 'claude-memory' THEN 0 WHEN 'project-instructions' THEN 1
                   WHEN 'gstack-learnings' THEN 2 ELSE 3 END, project, noticed_at"""
    return [
        {"path": r[0], "project": r[1], "digest": r[2], "noticed_at": r[3], "source": r[4]}
        for r in conn.execute(sql, params).fetchall()
    ]


def mark_ingested(conn, paths: list[str]) -> int:
    if not paths:
        return 0
    return conn.execute(
        """UPDATE public.pending_ingest SET ingested_at = now()
           WHERE path = ANY(%s) AND ingested_at IS NULL""",
        (paths,),
    ).rowcount
