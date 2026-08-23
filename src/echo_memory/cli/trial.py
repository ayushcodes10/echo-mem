"""echo-memory trial: rendering for the v1a exit-criteria instrumentation.

Every open item prints the exact command that records a verdict on it. That's
deliberate: the reason criterion 6 went untracked for the first days of the
trial isn't that anyone disagreed it mattered, it's that recording a judgement
had no obvious next keystroke. See trial/check.py for what counts as an open
item and trial/observations.py for what gets stored."""

from echo_memory.trial import observations

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
                lines.append(f"    {a_name}  <->  {b_name}   similarity {pair['similarity']:.3f}")
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
