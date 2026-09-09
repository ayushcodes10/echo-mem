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

- **It fires once, recorded not inferred.** The first version trusted Claude
  Code's `stop_hook_active` flag, which is set only while a session is
  *continuing* from a stop hook - once the agent answers and stops again it is a
  fresh stop with the flag clear. An eigen session hit this gate five times on
  2026-09-02 and spent 27 minutes unable to satisfy any of them. Gated sessions
  are now written to `stop_gate_fired` and never gated twice.
- **It is scoped to this project.** Blocking an echo-mem session because eigen
  has a backlog would train everyone to turn it off. Only files belonging to
  the project the session is actually in can hold it open.
- **It is silent when there is nothing.** The steady state after a drained
  queue is no output at all.
"""

import json
import os
import sys
from pathlib import Path

from echo_memory.cli import reconcile as reconcile_mod
from echo_memory.ingestion import activity, capture

# How many files to name in the block. Past a handful the reason stops reading
# as a task and starts reading as a wall, which is how the session-start
# briefing lost. The rest are counted, not listed.
MAX_LISTED = 5


def already_gated(conn, session_id: str | None) -> bool:
    if not session_id:
        return False
    return conn.execute(
        "SELECT 1 FROM public.stop_gate_fired WHERE session_id = %s", (session_id,)
    ).fetchone() is not None


def record_gated(conn, session_id: str | None, project: str, n_files: int) -> None:
    """Recorded before the reason is printed, so a crash between the two costs
    a missed nudge rather than an unbounded loop."""
    if not session_id:
        return
    conn.execute(
        """INSERT INTO public.stop_gate_fired (session_id, project, n_files)
           VALUES (%s, %s, %s) ON CONFLICT (session_id) DO NOTHING""",
        (session_id, project, n_files),
    )


def cli_path() -> str:
    """The absolute path to this CLI.

    The reason used to print a bare `echo-memory`, which is not on PATH for an
    install inside a virtualenv - so the one route that did not need the MCP
    tool did not work either, and the session had no way to comply at all."""
    from_env = os.environ.get("ECHO_MEMORY_BIN")
    if from_env:
        return from_env
    try:
        resolved = Path(sys.argv[0]).resolve()
        # Only when argv[0] really is this CLI. Imported into another runner -
        # pytest, a REPL - argv[0] is that runner, and printing "<pytest> pending
        # --done" would hand the agent a command that cannot work.
        if resolved.name == "echo-memory" and resolved.exists():
            return str(resolved)
    except OSError:
        pass
    return "echo-memory"


def gate(conn, project: str, root: Path | None = None) -> dict:
    """What this project still owes the graph.

    Sweeps before asking: a file written moments ago through a path the capture
    hook did not match would otherwise not be in the queue to gate on, and the
    end of the session is the last chance to catch it."""
    reconcile_mod.reconcile(conn, root=root, project=project)
    queued = capture.pending(conn, project)
    return {"project": project, "n": len(queued), "files": [q["path"] for q in queued]}


def render_unrecorded_reason(work: dict) -> str:
    """What to say to a session that did a lot and wrote nothing.

    Names the number, because a claim with a count attached is checkable by the
    agent reading it and one without is nagging. Offers the same escape hatch
    the file gate does: an honest "nothing durable happened" is a real answer,
    and a gate with no way out is one people switch off.
    """
    return "\n".join([
        f"This session changed {work['edits']} files and recorded nothing in memory.",
        "",
        (
            "That is the failure this tool exists to prevent, and it is not "
            "hypothetical: eight merged PRs in one window and two days of "
            "building a service both went by this way. The work reached commit "
            "messages and READMEs, which another tool cannot find - a Codex "
            "session looking for exactly that work on 2026-09-09 queried memory "
            "twenty times and correctly reported there was nothing there."
        ),
        "",
        (
            "Call write_episode now for whatever this session established: a "
            "decision and why, a correction, a constraint that cost time to "
            "find, something that would have to be re-explained to a different "
            "tool tomorrow. Write it so it still makes sense read cold in six "
            "months."
        ),
        "",
        (
            "If this session genuinely established nothing durable - a rename, "
            "a formatting pass, an experiment you abandoned - say so in one "
            "line and stop. That is a real answer and this will not ask again."
        ),
    ])


def render_reason(result: dict, bin_path: str | None = None) -> str:
    binary = bin_path or cli_path()
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
            "A file is listed because it changed on disk, which is not the same as "
            "its content being absent from the graph - a past session may have "
            "written the facts and never marked it done. Call query_memory on each "
            "file's subject first; if what it states is already recorded, mark it "
            "done rather than writing it twice. Otherwise call write_episode with "
            "the entities and facts it states. Either way, finish with:"
        ),
        "",
        # Two paths and an ellipsis: enough to show the shape of the command
        # without a line that wraps six times. The trailing marker appears
        # whenever there is anything beyond what is spelled out, so the
        # command is never mistaken for the complete list.
        f"  {binary} pending --done "
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
        "",
        # The escape hatch. This gate cannot see the session's tool list, so it
        # can block a session that has no way to comply - which is exactly what
        # happened to an eigen session on 2026-09-02: write_episode absent, the
        # CLI not on PATH, five stop hooks, 27 minutes spent. An unsatisfiable
        # demand with no stated way out is worse than no gate at all.
        (
            "If write_episode is not in your tool list and the command above does not "
            "run, you cannot satisfy this: say so plainly in one line and stop. Do not "
            "retry, and do not treat it as a task. This will not fire again for this "
            "session, and the files stay queued for one that can reach the tools."
        ),
    ]
    return "\n".join(lines)


def render_hook_output(result: dict, bin_path: str | None = None) -> str:
    """The JSON shape Claude Code reads from a Stop hook. `block` returns
    control to the agent with `reason` as its next instruction, which is the
    whole point: this has to act, not ask."""
    return json.dumps({"decision": "block", "reason": render_reason(result, bin_path)})


def run(args, config, conn) -> int:
    session_id = getattr(args, "session_id", None)
    if already_gated(conn, session_id):
        return 0

    result = gate(conn, config.project)
    if result["n"]:
        record_gated(conn, session_id, config.project, result["n"])
        print(render_hook_output(result) if args.hook_json else render_reason(result))
        return 0

    # No queued files does not mean nothing was owed. It usually means this
    # session never wrote a memory file, which is the larger of the two capture
    # failures and the one the gate could not previously see.
    work = activity.worked_without_recording(conn, session_id)
    if work["should_ask"]:
        record_gated(conn, session_id, config.project, 0)
        reason = render_unrecorded_reason(work)
        print(json.dumps({"decision": "block", "reason": reason})
              if args.hook_json else reason)
    return 0
