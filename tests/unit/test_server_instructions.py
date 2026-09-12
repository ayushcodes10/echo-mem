"""Every tool the loop depends on has to be named where agents will read it.

The MCP instruction block is the one thing a client is guaranteed to put in
front of a model. A tool that only exists in its own description is discovered
by a model already looking for it, which is the opposite of the case that
matters.

record_recall_save was missing from it for the whole of the first trial. That
is the one call criterion 6 counts, and the only one the instructions never
asked for - reads and writes are recorded by the code paths themselves, so the
single signal that needs a deliberate decision was also the single signal
nothing prompted. Seven were recorded in three weeks against hundreds of reads.
"""

from __future__ import annotations

import pytest

from echo_memory import server

# Every tool an agent has to call for the memory loop to close. Deliberately a
# literal list rather than something derived from the module: the point is to
# fail when a tool is added and nobody tells anyone about it, and a derived
# list would quietly agree with whatever happened.
LOOP_TOOLS = (
    "query_memory",
    "write_episode",
    "record_recall_save",
    "pending_documents",
    "mark_ingested",
)


@pytest.mark.parametrize("tool", LOOP_TOOLS)
def test_the_instructions_name_every_tool_the_loop_needs(tool):
    assert tool in server.server.instructions, (
        f"{tool} is not named in the MCP instructions, so a client that reads "
        "only those will never be told to call it"
    )


def test_the_save_instruction_keeps_its_honesty_guard():
    """Asking harder for a measurement is how the measurement gets inflated.
    The instruction has to carry the same brake the tool description does."""
    instructions = server.server.instructions

    assert "speculatively" in instructions
    assert "inflated count is worse than an empty one" in instructions


def test_the_tools_are_actually_there():
    """A name in the instructions that resolves to nothing is worse than
    silence: the model is told to call something that does not exist."""
    for tool in LOOP_TOOLS:
        assert callable(getattr(server, tool, None)), f"{tool} is advertised but missing"


def test_the_server_reports_a_version():
    """MCPServer defaults version to "", so a client that shows which server it
    is talking to displays a blank. The first question about a memory bug is
    which version wrote the fact, and the answer has to come from somewhere."""
    from echo_memory import __version__
    from echo_memory.server import server

    assert server.version == __version__
    assert server._lowlevel_server.create_initialization_options().server_version
