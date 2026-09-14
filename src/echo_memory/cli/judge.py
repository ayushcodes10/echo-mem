"""echo-memory judge: the evaluation whose questions predate its answers.

The commands are one workflow, and the order is the point. `new` records
questions and retrieves nothing. `open` retrieves, under every configuration at
once, and stamps the question so a later reader can see which came first.
`export` writes the shuffled union to a file to mark in an editor, `import`
reads it back, and `pool` does the same interactively. `score` reads the labels.

`judges`, `agreement` and `score --by` exist because one judge is one
measurement. A second pass over the same pool disagreed with the first on 11 of
142 pairs - always in the direction of more relevant, never fewer - and that
was enough to change which configuration leads on MRR. A single set of labels
cannot show that, so the tool refuses to score without being told whose.

Either way a fact already judged never reappears, so judging is resumable. The
file is the better surface and the reason is not convenience: a terminal prompt
needs a TTY, cannot be paused inside a session, shows one fact with no sense of
how many remain, and puts a judge under exactly the time pressure that produces
labels nobody should build on. A file can be left half-done, diffed, reviewed by
somebody else, and committed next to the result it produced.
"""

from __future__ import annotations

import sys

from echo_memory.eval import independent

# Scored together so one judging pass covers all of them. Keep this list short:
# every configuration added enlarges the pool a human has to label, and the
# marginal question is worth more than the marginal configuration.
CONFIGURATIONS = {
    "shipping": {},
    "vector only": {"vector_only": True},
    "lexical only": {"lexical_only": True},
    "+ graph hop": {"graph_hops": 1},
}


def _facts(conn, edge_ids: list[str]) -> dict[str, dict]:
    from echo_memory.retrieval.query_memory import _fetch_facts

    return _fetch_facts(conn, edge_ids)


def run(args, config, conn) -> int:
    group_id = config.group_id(args.scope)
    command = args.judge_command

    if command == "new":
        result = independent.add_question(
            conn, group_id, args.text,
            subject=getattr(args, "subject", None), author=config.user_id,
        )
        if result["created"]:
            print(f"Recorded question {result['id']}. Nothing has been retrieved for it.")
        else:
            print(f"Already recorded as question {result['id']}; left alone.")
        return 0

    if command == "list":
        rows = independent.questions(conn, group_id)
        if not rows:
            print("No questions yet. `echo-memory judge new \"<question>\"` records one.")
            return 0
        for q in rows:
            state = "open for judging" if q["opened_at"] else "not yet retrieved for"
            sha = q["retriever_sha"] or "no commit recorded"
            print(f"  {q['id']:>3}  [{state}]  ({sha})  {q['text']}")
        return 0

    if command == "open":
        from echo_memory.ingestion.embeddings import LocalEmbedder

        pending = independent.questions(conn, group_id, unopened_only=True)
        if not pending:
            print("Every question has already been opened. `judge pool` to label.")
            return 0
        embedder = LocalEmbedder()
        for q in pending:
            returned = independent.run_configurations(
                conn, group_id, q, embedder, CONFIGURATIONS
            )
            pooled = len({e for ids in returned.values() for e in ids})
            print(f"  {q['id']:>3}  {pooled} fact(s) pooled  {q['text'][:60]}")
        print(f"\nOpened {len(pending)} question(s). `judge pool` to label them.")
        return 0

    who = getattr(args, "judged_by", None) or config.user_id

    if command == "pool":
        return _pool(conn, group_id, getattr(args, "question", None), who)

    if command == "export":
        text = independent.export_pool(
            conn, group_id, only=getattr(args, "question", None), judged_by=who
        )
        out = getattr(args, "out", None)
        if out:
            from pathlib import Path

            Path(out).write_text(text, encoding="utf-8")
            print(f"Wrote {out}. Mark y or n between the brackets, then `judge import {out}`.")
        else:
            print(text, end="")
        return 0

    if command == "import":
        from pathlib import Path

        counts = independent.import_pool(
            conn, Path(args.file).read_text(encoding="utf-8"), judged_by=who
        )
        print(
            f"Recorded {counts['y']} relevant, {counts['n']} not"
            + (f", left {counts['skipped']} unmarked." if counts["skipped"] else ".")
        )
        return 0

    if command == "score":
        # Not config.user_id: scoring reads labels, it does not write them, and
        # defaulting to "whoever is running this" would quietly pick a judge.
        by = getattr(args, "judged_by", None)
        try:
            print(
                independent.render(
                    independent.score(conn, group_id, judged_by=by),
                    independent.coverage(conn, group_id, judged_by=by),
                ),
                end="",
            )
            if getattr(args, "per_question", False):
                print(independent.render_per_question(
                    independent.per_question(conn, group_id, judged_by=by)
                ))
        except ValueError as exc:
            print(f"{exc}\n  echo-memory judge score --by <name>", file=sys.stderr)
            return 1
        return 0

    if command == "compare":
        try:
            r = independent.compare_configurations(
                conn, group_id, args.a, args.b,
                judged_by=getattr(args, "judged_by", None),
            )
        except ValueError as exc:
            print(f"{exc}\n  echo-memory judge compare <a> <b> --by <name>", file=sys.stderr)
            return 1
        if not r["questions"]:
            print("Nothing judged relevant yet, so there is nothing to compare.")
            return 0
        print(f"\n  {r['b']} against {r['a']}, judged by {r['judged_by']}:\n")
        print(f"    delta MRR        {r['delta']:+.3f}")
        print(f"    95% interval     [{r['low']:+.3f}, {r['high']:+.3f}]  "
              f"over {r['questions']} question(s)")
        print("\n  " + (
            "The interval excludes zero. On this many questions that is worth "
            "something,\n  but read it next to the same comparison under another "
            "judge before believing it."
            if r["significant"] else
            "The interval includes zero. Whichever of these two leads, this many "
            "questions\n  cannot show it - and a lead that changes with the judge "
            "is the same statement\n  arrived at a second way."
        ) + "\n")
        return 0

    if command == "judges":
        rows = independent.judges(conn, group_id)
        if not rows:
            print("Nobody has judged this scope yet. `judge export` writes the pool out.")
            return 0
        for name, total, yes in rows:
            print(f"  {name:<20}{total:>6} label(s), {yes:>4} relevant")
        if len(rows) > 1:
            print("\nThese are separate measurements. `judge agreement <a> <b>` "
                  "compares two,\nand `judge score --by <name>` reads one.")
        return 0

    if command == "agreement":
        result = independent.agreement(conn, group_id, args.a, args.b)
        if not result["pairs"]:
            print(f"{args.a} and {args.b} have no pair in common.", file=sys.stderr)
            return 1
        print(f"\n  {args.a} and {args.b}, on the {result['pairs']} pair(s) both labelled:\n")
        print(f"    both relevant      {result['both_relevant']:>5}")
        print(f"    both not           {result['both_not']:>5}")
        print(f"    {args.a} only{'':<{max(0, 14 - len(args.a))}}{result[f'{args.a}_only']:>5}")
        print(f"    {args.b} only{'':<{max(0, 14 - len(args.b))}}{result[f'{args.b}_only']:>5}")
        print(f"\n    raw agreement      {result['raw_agreement']:>5.3f}")
        print(f"    Cohen's kappa      {result['kappa']:>5.3f}")
        print("\n  Read kappa, not raw agreement: almost every pair is irrelevant, so two")
        print("  judges who both say no to everything agree nearly always and have said")
        print("  nothing. Kappa is unstable when the positive class is this rare, which")
        print("  is why the counts are here beside it.\n")
        return 0

    print(f"unknown judge command {command!r}", file=sys.stderr)
    return 1


def _pool(conn, group_id: str, only: int | None, judged_by: str) -> int:
    """One fact at a time, with the question above it and no configuration named.

    The prompt deliberately does not say how many configurations returned this
    fact, or where any of them ranked it. Either would be a signal about which
    system found it, which is the one thing the judge must not have. Nor does
    it say what another judge said, for the same reason.
    """
    rows = independent.questions(conn, group_id)
    rows = [q for q in rows if q["opened_at"] and (only is None or q["id"] == only)]
    if not rows:
        print("Nothing to judge. `judge open` retrieves for the questions first.")
        return 0

    judged = 0
    for q in rows:
        pool = independent.pool(conn, q["id"], judged_by=judged_by)
        if not pool:
            continue
        facts = _facts(conn, pool)
        print(f"\n\033[1mQ{q['id']}: {q['text']}\033[0m")
        print(f"  {len(pool)} fact(s) to judge. y = answers it, n = does not, s = skip, q = stop.\n")
        for edge_id in pool:
            fact = facts.get(edge_id)
            if not fact:
                continue
            print(f"    {fact['fact']}")
            try:
                answer = input("    relevant? [y/n/s/q] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nStopped. Judgements so far are saved.")
                return 0
            if answer == "q":
                print(f"\nStopped after {judged} judgement(s); they are saved.")
                return 0
            if answer == "s":
                print()
                continue
            if answer not in ("y", "n"):
                print("    (not y or n - skipped)\n")
                continue
            independent.judge(
                conn, q["id"], edge_id, answer == "y", judged_by=judged_by
            )
            judged += 1
            print()

    print(f"\n{judged} judgement(s) recorded. `judge score` reads them back.")
    return 0
