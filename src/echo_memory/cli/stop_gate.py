"""echo-memory stop-check: hold a session open until what it learned is stored.

Every other surface here asks. The SessionStart briefing has said "run
`echo-memory pending`, read each, and write_episode what it states" since
2026-08-23. Between then and 2026-09-02 it was ignored in every session in every
project: 16 memory files were written across eigen and dugout, the capture hook
noticed all 16, and not one was turned into a fact by the session that wrote it.
The eventual ingest was done by hand, from a different project, ten days late.

The lesson from that window is not that the instruction was badly worded. It is
that instructions lose to whatever is structurally louder - Claude Code's own
file-based memory is a permanent system-prompt section, while this was one
reminder at session start competing with several hundred registered tools. The
things that worked in the same window were the hooks, because a hook does not
depend on anyone choosing to act.

So this is a hook. `Stop` fires when the agent is about to finish, which is
exactly when it still holds the context to say what it learned and is no longer
mid-task. Returning `{"decision": "block"}` hands the reason back to the agent
and lets it keep working, so a memory file written this session becomes a fact
in this session rather than a backlog item.

Three bounds keep it from becoming the thing people disable:

- **It fires once.** Claude Code sets `stop_hook_active` when a session is
  already continuing from a stop hook. Seeing that, this exits silently. One
  nudge per session, never a loop, even if the agent ignores it.
- **It is scoped to this project.** Blocking an echo-mem session because eigen
  has a backlog would train everyone to turn it off. Only files belonging to
  the project the session is actually in can hold it open.
- **It is silent when there is nothing.** The steady state after a drained
  queue is no output at all.
"""

import json
from pathlib import Path

from echo_memory.cli import reconcile as reconcile_mod
from echo_memory.ingestion import capture

# How many files to name in the block. Past a handful the reason stops reading
# as a task and starts reading as a wall, which is how the session-start
# briefing lost. The rest are counted, not listed.
MAX_LISTED = 5


def gate(conn, project: str, root: Path | None = None) -> dict:
    """What this project still owes the graph.

    Sweeps before asking: a file written moments ago through a path the capture
    hook did not match would otherwise not be in the queue to gate on, and the
    end of the session is the last chance to catch it."""
    reconcile_mod.reconcile(conn, root=root, project=project)
    queued = capture.pending(conn, project)
    return {"project": project, "n": len(queued), "files": [q["path"] for q in queued]}


def render_reason(result: dict) -> str:
    files = result["files"]
    shown, extra = files[:MAX_LISTED], len(files) - min(len(files), MAX_LISTED)
    lines = [
        (
            f"{result['n']} memory file(s) from '{result['project']}' hold things "
            "this session learned that are not in Echo Memory yet:"
        ),
        "",
    ]
    lines += [f"  {Path(p).name}  -  {p}" for p in shown]
    if extra:
        lines.append(f"  ...and {extra} more (`echo-memory pending` lists them all)")
    lines += [
        "",
        (
            "Read each one and call write_episode with the entities and facts it "
            "states, then mark them stored:"
        ),
        "",
        # Two paths and an ellipsis: enough to show the shape of the command
        # without a line that wraps six times. The trailing marker appears
        # whenever there is anything beyond what is spelled out, so the
        # command is never mistaken for the complete list.
        "  echo-memory pending --done "
        + " ".join(files[:2])
        + (" ..." if len(files) > 2 else ""),
        "",
        (
            "Write what the file actually says - the decision, the correction, the "
            "finding and why it holds. Do not summarise it into one vague fact."
        ),
        "",
        # The third outcome is the one a well-behaved session actually hits. The
        # MCP tool description says to call write_episode in the same turn as the
        # thing happens, and Claude Code then writes its own memory file, so the
        # queue sees a file whose content is already in the graph. Offering only
        # "write it" and "it holds nothing" told that session to write duplicates -
        # and a gate that fires on correct behaviour is a gate people switch off.
        (
            "Two other outcomes are fine, and both end in marking it done. If you "
            "already called write_episode for this content earlier in the session, "
            "check nothing is missing and mark it done - do not write it twice. If a "
            "file genuinely holds nothing durable, mark it done and say so."
        ),
    ]
    return "\n".join(lines)


def render_hook_output(result: dict) -> str:
    """The JSON shape Claude Code reads from a Stop hook. `block` returns
    control to the agent with `reason` as its next instruction, which is the
    whole point: this has to act, not ask."""
    return json.dumps({"decision": "block", "reason": render_reason(result)})


def run(args, config, conn) -> int:
    result = gate(conn, config.project)
    if not result["n"]:
        return 0
    print(render_hook_output(result) if args.hook_json else render_reason(result))
    return 0
