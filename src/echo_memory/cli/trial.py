"""echo-memory trial: the trial subcommand - what it does and how it reads.

Every open item prints the exact command that records a verdict on it. That's
deliberate: the reason criterion 6 went untracked for the first days of the
trial isn't that anyone disagreed it mattered, it's that recording a judgement
had no obvious next keystroke. See trial/check.py for what counts as an open
item and trial/observations.py for what gets stored."""

import sys
from datetime import UTC, datetime

import psycopg

from echo_memory.infra.project import UNKNOWN as UNKNOWN_PROJECT
from echo_memory.trial import check, observations

_KIND_LABELS = {
    observations.RECALL_SAVE: "recall save",
    observations.DUPLICATE_NODE: "duplicate node",
    observations.NOT_DUPLICATE: "not a duplicate",
    observations.BAD_MERGE: "bad merge",
    observations.MERGE_OK: "merge ok",
}


def render_start(result: dict) -> str:
    if result["already_started"]:
        return (
            f"Trial already started on {result['started_on']} "
            f"({result['cap_days']}-day cap). Nothing changed."
        )
    return f"Trial started on {result['started_on']}, {result['cap_days']}-day cap."


def render_recorded(kind: str, observation_id: int, note: str) -> str:
    return f"Recorded {_KIND_LABELS[kind]} #{observation_id}: {note}"


def render_criterion_six(report: dict, indent: str = "  ", show_hint: bool = True) -> list[str]:
    """The criterion 6 block, shared by `trial check` and `status` so the two
    can't drift into reporting the gate differently."""
    counts, met = report["counts"], report["met"]
    lines = []

    trial = report["trial"]
    if trial is None:
        lines.append(
            f"{indent}! trial clock not started - run `echo-memory trial start` "
            "so the 3-week cap is measured, not estimated"
        )
    elif trial["expired"]:
        lines.append(
            f"{indent}! day {trial['day']} of {trial['cap_days']}: the cap is a hard cap "
            f"(started {trial['started_on']}). Decide on the gate now, don't extend."
        )
    else:
        lines.append(
            f"{indent}day {trial['day']} of {trial['cap_days']} "
            f"(started {trial['started_on']}, {trial['days_left']} left)"
        )

    saves_note = ""
    if counts["same_tool_saves"]:
        saves_note = (
            f" (+{counts['same_tool_saves']} same-tool, which the criterion doesn't count)"
        )
    lines.append(
        f"{indent}[{'x' if met['saves'] else ' '}] {counts['cross_tool_saves']}"
        f"/{observations.REQUIRED_SAVES} recall saves to a different tool{saves_note}"
    )
    # An unmet bar has to name its cause. A reader who sees 3/3 saves and an
    # unticked box would otherwise assume a display bug rather than a store
    # that cannot yet evidence what the bar measures.
    if report.get("unattributed_facts"):
        lines.append(
            f"{indent}    ! {report['unattributed_facts']} fact(s) still carry "
            f"agent_id '{UNKNOWN_PROJECT}', so a cross-tool save cannot be evidenced "
            "- run `alembic upgrade head`"
        )
    lines.append(
        f"{indent}[{'x' if met['duplicates'] else ' '}] {counts['duplicates']} "
        f"confirmed duplicate nodes (at most {observations.MAX_DUPLICATES} allowed)"
    )
    lines.append(
        f"{indent}[{'x' if met['bad_merges'] else ' '}] {counts['bad_merges']} "
        f"confirmed bad merges (must be {observations.MAX_BAD_MERGES})"
    )

    if report["n_open_pairs"] or report["n_unreviewed"]:
        waiting = []
        if report["n_open_pairs"]:
            waiting.append(f"{report['n_open_pairs']} similar node pair(s)")
        if report["n_unreviewed"]:
            waiting.append(f"{report['n_unreviewed']} entity resolution(s)")
        hint = " - run `echo-memory trial check`" if show_hint else ""
        lines.append(f"{indent}! {' and '.join(waiting)} awaiting review{hint}")
    if report.get("n_suppressed_pairs"):
        # Always shown, even when nothing else is waiting: a hidden backlog
        # that renders as an empty list is worse than a visible one.
        lines.append(
            f"{indent}  ({report['n_suppressed_pairs']} more pair(s) span unrelated "
            "projects, hidden by default - add --all-projects to review them)"
        )
    return lines


def render_check(report: dict) -> str:
    lines = ["Echo Memory - v1a criterion 6 (the v1a -> v1b gate)", ""]
    lines += render_criterion_six(report, show_hint=False)
    lines.append("")

    any_open = False
    for scope, items in report["open"].items():
        pairs, resolutions = items["duplicate_candidates"], items["unreviewed_resolutions"]
        if not pairs and not resolutions:
            continue
        any_open = True
        lines.append(f"{scope}:")

        if pairs:
            lines.append("  Similar nodes that stayed separate - one entity split in two?")
            for pair in pairs:
                a_id, b_id = pair["node_ids"]
                a_name, b_name = pair["names"]
                where = " ".join(pair.get("projects", []))
                marker = "" if pair.get("same_project", True) else "  [cross-project]"
                lines.append(
                    f"    {a_name}  <->  {b_name}   similarity {pair['similarity']:.3f}{marker}"
                )
                if where:
                    lines.append(f"      in: {where}")
                lines.append(
                    f"      same entity:  echo-memory --scope {scope} trial dup "
                    f'{a_id} {b_id} "<why>"'
                )
                lines.append(
                    f"      different:    echo-memory --scope {scope} trial not-dup "
                    f'{a_id} {b_id} "<why>"'
                )
            lines.append("")

        if resolutions:
            lines.append("  Entity resolutions not yet reviewed - two entities merged into one?")
            for r in resolutions:
                when = r["timestamp"].strftime("%Y-%m-%d %H:%M UTC")
                lines.append(f"    #{r['audit_entry_id']}  {r['node_name']}  ({when})")
                lines.append(f"      {r['resolution_detail']}  [session {r['session_id']}]")
                lines.append(
                    f"      correct:   echo-memory --scope {scope} trial merge-ok "
                    f"{r['audit_entry_id']}"
                )
                lines.append(
                    f"      incorrect: echo-memory --scope {scope} trial bad-merge "
                    f'{r["audit_entry_id"]} "<why>"'
                )
            lines.append("")

    if not any_open:
        if report.get("n_suppressed_pairs"):
            lines.append(
                f"Nothing awaiting review in-project. {report['n_suppressed_pairs']} pair(s) "
                "span unrelated projects and are hidden; add --all-projects to see them."
            )
        else:
            lines.append("Nothing awaiting review.")
        lines.append("")

    lines.append(
        "Recall saves aren't detectable from stored data - when a recalled fact saves you "
        're-explaining something, log it: `echo-memory trial save "<what>" --from <tool>`.'
    )
    return "\n".join(lines) + "\n"


def render_log(entries: list[dict]) -> str:
    if not entries:
        return "No trial observations recorded yet.\n"

    lines = [f"Echo Memory - {len(entries)} trial observation(s)", ""]
    for e in entries:
        when = e["timestamp"].strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"#{e['id']}  {when}  {_KIND_LABELS[e['kind']]}")
        lines.append(f'    "{e["note"]}"')
        if e["kind"] == observations.RECALL_SAVE:
            lines.append(f"    written by {e['written_by']} -> recalled by {e['recalled_by']}")
        if e["node_ids"]:
            lines.append(f"    nodes {', '.join(e['node_ids'])}")
        if e["audit_entry_id"]:
            lines.append(f"    audit entry #{e['audit_entry_id']}")
    return "\n".join(lines) + "\n"


def run(args, config, conn) -> int:
    group_id = config.group_id(args.scope)

    if args.trial_command == "start":
        started_on = args.on or datetime.now(UTC).date()
        print(render_start(observations.start_trial(conn, started_on, args.cap_days)))
        return 0

    if args.trial_command == "check":
        report = check.build_report(
            conn, config, include_exact=args.include_exact, all_projects=args.all_projects
        )
        print(render_check(report), end="")
        return 0

    if args.trial_command == "log":
        group_ids = [config.group_id(scope) for scope in ("solo", "shared")]
        print(render_log(observations.list_observations(conn, group_ids)), end="")
        return 0

    if args.trial_command == "save":
        kind = observations.RECALL_SAVE
        fields = {
            "written_by": args.written_by,
            "recalled_by": args.recalled_by or config.agent_id,
        }
    elif args.trial_command in ("dup", "not-dup"):
        kind = (
            observations.DUPLICATE_NODE
            if args.trial_command == "dup"
            else observations.NOT_DUPLICATE
        )
        fields = {"node_ids": [args.node_a, args.node_b]}
    else:
        kind = (
            observations.BAD_MERGE if args.trial_command == "bad-merge" else observations.MERGE_OK
        )
        fields = {"audit_entry_id": args.audit_entry_id}

    try:
        if "node_ids" in fields:
            fields["node_ids"] = observations.sort_pair(fields["node_ids"])
        recorded = observations.record(conn, group_id, kind, args.note, **fields)
        observation_id = recorded["id"]
    except observations.TrialError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except psycopg.errors.UniqueViolation:
        # The unique indexes exist so a second verdict on the same pair or the
        # same resolution can't quietly overwrite the first one.
        print(
            "error: that pair or resolution already has a recorded verdict "
            "(see `echo-memory trial log`)",
            file=sys.stderr,
        )
        return 1
    except psycopg.errors.ForeignKeyViolation:
        print(
            f"error: no audit entry #{args.audit_entry_id} "
            "(ids come from `echo-memory trial check`)",
            file=sys.stderr,
        )
        return 1

    if not recorded["created"]:
        print(f"Already recorded as #{observation_id}; nothing changed.")
        return 0

    print(render_recorded(kind, observation_id, args.note))
    if kind == observations.RECALL_SAVE and args.written_by == (
        args.recalled_by or config.agent_id
    ):
        print(
            "note: written and recalled by the same tool, so this doesn't count toward "
            "criterion 6's cross-tool bar."
        )
    return 0
