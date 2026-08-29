"""echo-memory skill: the usage instructions, as text you can paste.

Every other surface installs itself. Claude Code gets `.claude/skills/`, a
`SKILL.md` and four hooks; Cursor gets an always-applied project rule. Claude
Desktop has no hooks, no rules file and no per-project config on disk, so there
is nowhere to write anything - the only durable instruction channel is a
Project's custom instructions, which a human types in.

That gap had a measurable cost. Claude Desktop was correctly registered, with
its own agent id, and its MCP log showed six successful connections and three
`tools/list` calls - and zero `tools/call`. Ever. The tools were available and
nothing ever told the model to reach for them, which is the same failure
`cli/recall.py` records for Claude Code: "the plumbing was fine; remembering was
the problem."

So this prints the text rather than writing a file. Paste it once into a Claude
Desktop Project and every conversation in that project carries it."""

from echo_memory.cli.install import skill_text

_HEADER = """\
Paste everything below into a Claude Desktop Project's custom instructions
(Projects -> your project -> Instructions). Claude Desktop has no hooks and no
rules file, so this is the only place instructions persist across conversations.

Then work inside that project. Facts written there are attributed to
claude-desktop, which is what makes a recall in another tool count as
cross-tool.

------------------------------ paste from here ------------------------------
"""

_FOOTER = """\
------------------------------- to here -------------------------------------

Check it is working: write something factual in that project, then run
`echo-memory status`. A `claude-desktop` row should appear under "written by".
"""


def render_skill(client: str = "claude-desktop") -> str:
    """The instruction text, with paste guidance for a client that needs it."""
    body = skill_text()
    if client == "generic":
        return body if body.endswith("\n") else body + "\n"
    if not body.endswith("\n"):
        body += "\n"
    return _HEADER + body + _FOOTER
