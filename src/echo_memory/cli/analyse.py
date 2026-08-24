"""First-run project comprehension: what to read, and what to write down.

A first session in an existing project starts with an empty memory even though
the project is months old. Bootstrap sweeps memory *files*; a project that
never had any is still a blank page, and everything the codebase knows about
itself is nowhere.

This module does not do the analysis. It finds the best available sources and
tells the agent what to read and what kind of fact is worth keeping. The
judgement - which forty things about a codebase matter - is the agent's,
because the server never calls an LLM.

Importing a structural graph instead was considered and rejected. graphify
already builds one and it is the right tool for "where is this code and what
calls it"; for eigen that graph is 9,321 nodes against this store's 115 facts,
so merging them would bury every recorded decision under file names. The two
graphs answer different questions. What this pass wants from graphify is its
GRAPH_REPORT.md - a narrative summary a human wrote tooling to produce - not
its node list."""

from pathlib import Path

# Ordered by how much project understanding a page tends to carry per line.
# graphify's report is first when present because it is already a synthesis;
# git history is last because subjects are hints, not explanations.
_SOURCES = (
    ("graphify-out/GRAPH_REPORT.md", "architecture report (graphify synthesis)"),
    ("README.md", "what the project is and who it is for"),
    ("ARCHITECTURE.md", "architecture"),
    ("DESIGN.md", "design system and conventions"),
    ("IMPLEMENTATION_STATUS.md", "what is built and what is not"),
    ("CLAUDE.md", "project instructions and conventions"),
    ("AGENTS.md", "project instructions and conventions"),
    ("CONTRIBUTING.md", "workflow and conventions"),
    ("TODOS.md", "known deferrals and their reasons"),
    ("docs/designs", "design docs"),
    ("docs", "documentation"),
)

# Enough to be genuinely useful, few enough that a first pass ends. A project
# whose memory is forty good facts is well served; one with four hundred is a
# haystack, and retrieval degrades with noise (see the design doc's premise on
# why plain vector search over everything stops working).
SUGGESTED_MIN_FACTS = 15
SUGGESTED_MAX_FACTS = 60


def find_sources(root: Path) -> list[dict]:
    """The comprehension inputs that actually exist in this project."""
    found = []
    for relative, why in _SOURCES:
        path = root / relative
        if path.is_file():
            found.append({"path": str(path), "kind": why, "is_dir": False})
        elif path.is_dir():
            docs = sorted(p for p in path.glob("*.md") if p.is_file())[:5]
            if docs:
                found.append(
                    {"path": str(path), "kind": why, "is_dir": True,
                     "files": [str(d) for d in docs]}
                )
    return found


def has_been_analysed(conn, project: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM public.project_analysis WHERE project = %s", (project,)
    ).fetchone()
    return row is not None


def mark_analysed(conn, project: str, n_facts: int, sources: list[str]) -> None:
    conn.execute(
        """INSERT INTO public.project_analysis (project, analysed_at, n_facts, sources)
           VALUES (%s, now(), %s, %s)
           ON CONFLICT (project) DO UPDATE
               SET analysed_at = now(), n_facts = EXCLUDED.n_facts,
                   sources = EXCLUDED.sources""",
        (project, n_facts, sources),
    )


def render_instruction(project: str, sources: list[dict]) -> str:
    """What the agent is asked to do. Written as instructions because that is
    who reads it - out of the session-start briefing."""
    lines = [
        (
            f"Echo Memory has nothing recorded for project '{project}' yet, and this "
            "project already exists. Do a one-time comprehension pass before you start work."
        ),
    ]
    if sources:
        lines.append("Read these, best first:")
        for source in sources:
            if source.get("is_dir"):
                lines.append(f"- {source['path']}/ ({source['kind']}): "
                             + ", ".join(Path(f).name for f in source["files"]))
            else:
                lines.append(f"- {source['path']} ({source['kind']})")
    else:
        lines.append(
            "No README or docs found, so read the entry points and the most-changed "
            "files instead, and check `git log --oneline -30`."
        )
    lines += [
        "Also skim `git log --oneline -30` for what has been happening recently.",
        (
            f"Then call write_episode with {SUGGESTED_MIN_FACTS}-{SUGGESTED_MAX_FACTS} facts "
            "that would save a future session re-deriving them: what the project is and who "
            "it serves, its architecture and the boundaries that matter, how it builds, "
            "tests and deploys, conventions someone would otherwise violate, and any gotcha "
            "or non-obvious constraint the docs call out."
        ),
        (
            "Write facts, not an inventory. \"deploys from master, never merge dev\" is worth "
            "keeping; \"there is a file called utils.py\" is not - code structure questions "
            "belong to graphify, not here. Each fact should still make sense read cold in six "
            "months, so name things rather than saying \"it\"."
        ),
        "When you're done: `echo-memory analyse --done` to record that this ran.",
    ]
    return "\n".join(lines)
