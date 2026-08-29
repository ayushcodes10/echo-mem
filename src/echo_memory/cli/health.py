"""echo-memory health: whether this graph is in good shape, and what to do about it.

Every other command answers a question you already had. This one exists to be
run when you have no question - to make the graph's condition legible without
querying it, and to say plainly when something is wrong that you would otherwise
discover weeks later.

The failure it is built against is real and recent. Criterion 6 read 0/3 for
nine days while the store looked healthy by every number the CLI reported: 160
facts, 24 projects, no duplicates, no bad merges. What those numbers hid was
that 142 of the facts were bulk imports, the last organic write was six days
old, and only one of two wired agents had ever written anything. Each of those
was visible in the data and none of them was surfaced.

The score is a heuristic, and deliberately a blunt one. It is not a measurement
of memory quality - nothing here knows whether a recalled fact was useful. It
weights the things that are checkable and that silently rot: whether anything is
still being written, whether more than one agent writes, whether entities are
connected, and whether the review queue is being kept up with.

Nothing here is gated. The paid tiers sell hosting and the things that only
exist when several people share a graph; diagnostics about your own data are not
a thing to withhold from the person whose data it is."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from echo_memory.cli import adopt
from echo_memory.cli.graph import fetch_graph
from echo_memory.graph import communities
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.trial import check as trial_check

# Days without a written fact before the store is treated as going cold. Chosen
# against observed behaviour rather than theory: this store wrote on three
# consecutive days and then stopped, and a week of silence is long enough that
# the habit is gone rather than the week being quiet.
STALE_AFTER_DAYS = 7

# Pairs waiting on a human before the queue counts as unattended. Under a dozen
# is an afternoon; sixty is a queue nobody is going to open.
REVIEW_BACKLOG = 20


def _last_write(conn, group_ids: list[str]) -> tuple[datetime | None, int, int]:
    """When a fact was last created, and how many were organic vs imported.

    Imports are swept from memory files that already existed. Counting them as
    activity is what let a store with six days of silence look busy."""
    rows = conn.execute(
        """
        SELECT
            max(timestamp) FILTER (WHERE session_id NOT LIKE '%%bootstrap%%'
                                     AND session_id NOT LIKE '%%backfill%%'),
            count(*) FILTER (WHERE session_id NOT LIKE '%%bootstrap%%'
                               AND session_id NOT LIKE '%%backfill%%'),
            count(*) FILTER (WHERE session_id LIKE '%%bootstrap%%'
                                OR session_id LIKE '%%backfill%%')
        FROM public.audit_entry
        WHERE mutation_type = 'created' AND group_id = ANY(%s)
        """,
        (group_ids,),
    ).fetchone()
    return (rows[0], rows[1] or 0, rows[2] or 0) if rows else (None, 0, 0)


def _writers(conn, group_ids: list[str]) -> dict[str, int]:
    """Facts written per agent id, read from the graph rather than from
    `fetch_graph`, whose rows do not carry the author."""
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->()
            WHERE e.group_id IN $gids AND e.t_invalid IS NULL
            RETURN e.agent_id
        $$, %s) AS (agent_id agtype)""",
        (json.dumps({"gids": list(group_ids)}),),
    ).fetchall()
    counts: dict[str, int] = {}
    for (agent_id,) in rows:
        name = str(agent_id).strip('"')
        counts[name] = counts.get(name, 0) + 1
    return counts


def _orphans(graph: dict) -> list[dict]:
    """Entities no fact connects to anything. A node with no edges cannot be
    reached by traversal and contributes nothing a flat list would not."""
    connected = {f["source_id"] for f in graph["facts"]}
    connected |= {f["target_id"] for f in graph["facts"]}
    return [n for n in graph["nodes"] if n["id"] not in connected]


def collect(conn, config, today: datetime | None = None) -> dict:
    """Everything health reports, as data. Rendering is separate so `--json`
    and the human view can never drift."""
    today = today or datetime.now(UTC)
    group_ids = [config.group_id(s) for s in ("solo", "shared")]

    graphs = {s: fetch_graph(conn, config.group_id(s)) for s in ("solo", "shared")}
    nodes = [n for g in graphs.values() for n in g["nodes"]]
    facts = [f for g in graphs.values() for f in g["facts"]]

    last, organic, imported = _last_write(conn, group_ids)
    days_quiet = (today - last).days if last else None

    edges = [(f["source_id"], f["target_id"]) for f in facts]
    detected = communities.detect({n["id"]: n["name"] for n in nodes}, edges)

    writers = _writers(conn, group_ids)
    wired = {c["agent_id"] for c in adopt.adopted_clients()}
    silent = sorted(wired - {a for a, n in writers.items() if n})

    report = trial_check.build_report(conn, config, today=today.date())
    orphans = [n for g in graphs.values() for n in _orphans(g)]

    return {
        "nodes": len(nodes),
        "facts": len(facts),
        "organic_writes": organic,
        "imported_writes": imported,
        "last_write": last.date().isoformat() if last else None,
        "days_since_write": days_quiet,
        "writers": writers,
        "silent_agents": silent,
        "orphans": [{"name": n["name"], "type": n["type"]} for n in orphans],
        "components": len(set(detected["components"].values())) if nodes else 0,
        "clusters": len(detected["communities"]),
        "unreviewed_pairs": report["n_open_pairs"],
        "unattributed_facts": report.get("unattributed_facts", 0),
        "duplicates": report["counts"]["duplicates"],
        "bad_merges": report["counts"]["bad_merges"],
    }


def score(h: dict) -> int:
    """0-100, and honestly a heuristic.

    Deductions are sized by how badly the thing distorts what the store appears
    to be, not by how hard it is to fix. Silence and single-authorship are the
    two that made a store look healthy while criterion 6 could not move, so they
    cost the most."""
    if not h["facts"]:
        return 0
    points = 100
    quiet = h["days_since_write"]
    if quiet is None:
        points -= 40
    elif quiet > STALE_AFTER_DAYS:
        points -= min(30, 10 + (quiet - STALE_AFTER_DAYS) * 2)
    real_writers = [a for a, n in h["writers"].items() if n and a != "unknown"]
    if len(real_writers) < 2:
        points -= 20
    if h["silent_agents"]:
        points -= 10
    if h["facts"]:
        orphan_share = len(h["orphans"]) / max(h["nodes"], 1)
        points -= int(min(15, orphan_share * 50))
    if h["unreviewed_pairs"] > REVIEW_BACKLOG:
        points -= 10
    points -= min(15, h["unattributed_facts"])
    points -= h["duplicates"] * 5
    points -= h["bad_merges"] * 10
    return max(0, min(100, points))


def findings(h: dict) -> tuple[list[str], list[str], list[str]]:
    """(strong, attention, recommendations). Attention items name the number and
    the thing to do; a diagnostic that does not tell you the next move is a
    complaint."""
    strong, attention, rec = [], [], []

    if h["duplicates"] == 0:
        strong.append("no duplicate nodes confirmed")
    if h["bad_merges"] == 0:
        strong.append("no bad merges confirmed")
    if h["unattributed_facts"] == 0 and h["facts"]:
        strong.append("every fact has a recorded author")
    if h["clusters"] > 1:
        strong.append(f"{h['clusters']} distinct clusters, so structure is forming")

    quiet = h["days_since_write"]
    if not h["facts"]:
        attention.append("no facts recorded yet")
        rec.append("Write something: memory only pays back what it was given.")
    elif quiet is None or quiet > STALE_AFTER_DAYS:
        attention.append(
            f"{quiet} days since the last write (last: {h['last_write']})"
            if quiet is not None else "nothing has ever been written"
        )
        rec.append(
            "Writes are agent-discretionary, so silence usually means nothing is "
            "prompting them rather than that nothing happened."
        )

    if h["imported_writes"] > h["organic_writes"]:
        attention.append(
            f"{h['imported_writes']} of {h['imported_writes'] + h['organic_writes']} "
            "facts came from bulk import, not from working"
        )

    real_writers = [a for a, n in h["writers"].items() if n and a != "unknown"]
    if len(real_writers) < 2:
        attention.append(
            f"only {real_writers[0]} has ever written, so recall cannot be cross-tool"
            if real_writers else
            "nothing has written a fact yet, so recall cannot be cross-tool"
        )
        rec.append("Run `echo-memory adopt` to wire another client, then use it.")

    if h["silent_agents"]:
        attention.append(
            "wired but has never written: " + ", ".join(h["silent_agents"])
        )
        rec.append(
            "A wired client that writes nothing usually lacks instructions rather "
            "than access - `echo-memory skill` prints them."
        )

    if h["orphans"]:
        attention.append(
            f"{len(h['orphans'])} entities connect to nothing "
            f"(e.g. {', '.join(o['name'] for o in h['orphans'][:3])})"
        )
        rec.append("Orphans are unreachable by traversal; relate them or let them go.")

    if h["unreviewed_pairs"] > REVIEW_BACKLOG:
        attention.append(f"{h['unreviewed_pairs']} similar pairs awaiting review")
        rec.append("Run `echo-memory trial check` to judge them before the queue is ignored.")

    if h["unattributed_facts"]:
        attention.append(f"{h['unattributed_facts']} facts have no recorded author")
        rec.append("Run `alembic upgrade head` to backfill attribution.")

    return strong, attention, rec


def render(h: dict) -> str:
    strong, attention, rec = findings(h)
    n = score(h)
    bar = "#" * (n // 5) + "." * (20 - n // 5)
    lines = [
        "Echo Memory - knowledge health",
        "",
        f"  {n}/100  [{bar}]",
        (
            f"  {h['facts']} facts, {h['nodes']} entities, "
            f"{h['clusters']} clusters, {h['components']} unrelated groups"
        ),
        # Always shown, warning or not. A threshold decides when to complain;
        # it should not decide whether the reader gets to see the number.
        (
            f"  {h['organic_writes']} written while working, last on {h['last_write']}"
            f" ({h['days_since_write']}d ago)"
            if h["last_write"] else "  nothing written while working yet"
        ),
        "",
    ]
    if strong:
        lines.append("  strong")
        lines += [f"    + {s}" for s in strong]
        lines.append("")
    if attention:
        lines.append("  attention")
        lines += [f"    ! {a}" for a in attention]
        lines.append("")
    if rec:
        lines.append("  what to do")
        lines += [f"    - {r}" for r in rec]
        lines.append("")
    if not attention:
        lines.append("  Nothing needs attention.")
        lines.append("")
    return "\n".join(lines)
