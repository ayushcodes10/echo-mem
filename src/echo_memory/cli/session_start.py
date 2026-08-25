"""The session-start briefing: what memory already knows, injected before the
agent does anything.

This exists because of a circular gap the trial exposed. `write_episode` is
discretionary - the agent must choose to call it - and the nudge saying work is
queued was delivered *inside* `query_memory`'s response, so an agent only
learned memory existed if it had already used memory. A session that called
neither tool never heard anything, silently. Zero organic writes in two days is
what that looks like from the outside.

A SessionStart hook is the one moment guaranteed to happen in every session in
every project, and Claude Code injects `hookSpecificOutput.additionalContext`
deterministically rather than leaving it to the model to notice. So this is the
place to say: memory is here, here is what it knows about this project, here is
what is queued, and here is when to write.

Kept short on purpose. This lands in every session's context whether or not it
turns out to be relevant, so it pays rent by being brief and specific to the
project rather than a wall of instructions the model learns to skim."""

import json
import os
from pathlib import Path

from echo_memory.cli import analyse
from echo_memory.infra.db import GRAPH_NAME as GRAPH
from echo_memory.ingestion import capture
from echo_memory.trial import observations

# How many recent facts to quote. Enough to prove memory has something real
# about this project; few enough that the briefing stays a paragraph.
RECENT_FACTS = 4
FACT_PREVIEW_CHARS = 160


def _facts_for_project(conn, group_id: str, project: str) -> list[dict]:
    rows = conn.execute(
        f"""SELECT * FROM cypher('{GRAPH}', $$
            MATCH (a)-[e:FACT {{group_id: $gid, project: $project}}]->(b)
            WHERE e.t_invalid IS NULL
            RETURN a.name, b.name, e.relation_type, e.fact, e.t_valid
            ORDER BY e.t_valid DESC
        $$, %s) AS (source agtype, target agtype, relation agtype,
                     fact agtype, t_valid agtype)""",
        (json.dumps({"gid": group_id, "project": project}),),
    ).fetchall()
    return [
        {
            "source": str(r[0]).strip('"'),
            "target": str(r[1]).strip('"'),
            "relation": str(r[2]).strip('"'),
            "fact": str(r[3]).strip('"'),
        }
        for r in rows
    ]


def build_brief(conn, config, project: str, root: Path | None = None) -> dict:
    """Everything the briefing needs, in one place so the renderer stays dumb
    and the whole thing stays testable without a hook harness."""
    facts = _facts_for_project(conn, config.group_id("shared"), project)
    facts += _facts_for_project(conn, config.group_id("solo"), project)
    pending = capture.pending(conn)
    counts = observations.counts(
        conn, [config.group_id(scope) for scope in ("solo", "shared")]
    )
    # Ask for a comprehension pass only when the project is genuinely blank and
    # has not had one. Any fact existing stops the prompt, so an agent that
    # writes something and forgets to mark it done is not asked again next
    # session and cannot pile up duplicate passes.
    root = root or Path(os.getcwd())
    needs_analysis = not facts and not analyse.has_been_analysed(conn, project)
    sources = analyse.find_sources(root) if needs_analysis else []

    return {
        "project": project,
        "root": str(root),
        "needs_analysis": needs_analysis,
        "analysis_sources": sources,
        "n_facts": len(facts),
        "recent": facts[:RECENT_FACTS],
        "n_pending": len(pending),
        "pending_projects": sorted({p["project"] for p in pending}),
        "cross_tool_saves": counts["cross_tool_saves"],
        "required_saves": observations.REQUIRED_SAVES,
    }


def render_brief(brief: dict) -> str:
    """One paragraph of context, instruction first.

    Order matters and was learned the hard way. The first version led with the
    fact list - roughly 640 characters of evidence before it ever said what to
    do. On 2026-08-25 it fired alongside three other SessionStart hooks in the
    same instant, and the session that received it made 31 tool calls without a
    single memory call. Evidence buried the instruction. Now the instruction
    goes first and the facts are what backs it up."""
    lines = []

    if brief.get("needs_analysis"):
        lines.append(analyse.render_instruction(brief["project"], brief["analysis_sources"]))
        lines.append("")

    lines.append(
        "Echo Memory is active for this project. Before asking the user anything they may "
        "have already explained, call query_memory. Record decisions, corrections, "
        "preferences and hard-won findings with write_episode in the same turn they "
        "happen. If a recalled fact saved re-explaining something a different tool wrote, "
        "call record_recall_save."
    )

    if brief["n_pending"]:
        where = ", ".join(brief["pending_projects"][:4])
        lines.append(
            f"{brief['n_pending']} memory file(s) are queued but not yet recorded as facts "
            f"({where}). Run `echo-memory pending`, read each, and write_episode what it states."
        )

    if brief["n_facts"]:
        lines.append(
            f"It already holds {brief['n_facts']} fact(s) for '{brief['project']}', including:"
        )
        for fact in brief["recent"]:
            text = fact["fact"]
            if len(text) > FACT_PREVIEW_CHARS:
                text = text[:FACT_PREVIEW_CHARS].rstrip() + "..."
            lines.append(f"- {fact['source']} --{fact['relation']}--> {fact['target']}: {text}")
    elif not brief.get("needs_analysis"):
        lines.append(f"It holds nothing for '{brief['project']}' yet.")

    if brief["cross_tool_saves"] < brief["required_saves"]:
        lines.append(
            f"(Trial: {brief['cross_tool_saves']}/{brief['required_saves']} cross-tool "
            "recall saves recorded so far.)"
        )
    return "\n".join(lines)


def render_hook_output(context: str) -> str:
    """The JSON shape Claude Code reads from a SessionStart hook. additionalContext
    is injected deterministically, which is the entire reason this is a hook and
    not an instruction in a file the model may skim past."""
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
    )
