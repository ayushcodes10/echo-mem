"""An evaluation whose questions were not written from its answers.

`eval/retrieval.py` builds a query out of the fact it wants back. That makes
labels free, and it is why every number it produces describes the generated
task rather than retrieval. Two review rounds established the stronger version
of that limitation: a biased task can change WHICH CONFIGURATION WINS, not only
the level of both, so the harness cannot settle what should ship. The recorded
sign reversal - dropping the lexical channel measured +0.120 MRR under one
query shape and -0.088 under another - is an instance.

This is the other half. The independence that matters is from the gold-answer
construction and from the tuning, and it is enforced by order and by shape:

  1. A question is written and stored BEFORE anything is retrieved for it. It
     cannot have been fitted to a result that did not exist yet.
  2. The retriever is frozen at a commit, recorded on the question and again on
     every run. A question and a score from different code are two
     measurements.
  3. Every configuration runs, and their results are POOLED and shuffled. The
     judge sees a question and a list of facts, never a configuration.
  4. Relevance is judged for a (question, fact) pair. One label serves every
     configuration, and any number of facts may be relevant - which is what
     the old harness could not express, since it marked exactly one fact
     correct for a name that may appear in thirty.

**Pooling bias is not solved by any of this.** A fact no configuration
returned is never judged, so recall here is recall over the pooled relevant
set, never over the store. Reported as such, everywhere it appears.

The author may write the questions. Independence from the author is not what
was ever at stake - a person who knows the subject matter is the only person
who can ask a real question about it - and demanding it would make the
evaluation impossible rather than sound. What must not happen is a question
shaped by an answer, a score compared across code versions, or a judge who
knows which system produced a candidate. Those are the three this prevents.
"""

from __future__ import annotations

import random
import subprocess

# Judging order is shuffled so position carries no information about which
# configuration found a fact. Seeded so a judging session can be reproduced
# and audited.
SHUFFLE_SEED = 20260913


def retriever_sha() -> str | None:
    """The commit the retriever is frozen at, or None outside a checkout.

    Recorded on the question and again on every run. The paper has already
    published one pair of numbers from two different code versions by
    accident; this is the field that makes that visible rather than silent.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha or None


def add_question(conn, group_id: str, text: str, *, subject: str | None = None,
                 author: str | None = None) -> dict:
    """Record a question. Nothing is retrieved here, deliberately.

    Returns {"id": int, "created": bool}; a repeat of the same text in the same
    scope is a no-op rather than a second question, because two identical
    questions would be judged twice and counted twice.
    """
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("a question needs text")

    row = conn.execute(
        """INSERT INTO public.eval_question (group_id, text, subject, retriever_sha, author)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (group_id, text) DO NOTHING
           RETURNING id""",
        (group_id, text, subject, retriever_sha(), author),
    ).fetchone()
    if row is not None:
        return {"id": row[0], "created": True}
    existing = conn.execute(
        "SELECT id FROM public.eval_question WHERE group_id = %s AND text = %s",
        (group_id, text),
    ).fetchone()
    return {"id": existing[0], "created": False}


def questions(conn, group_id: str, *, unopened_only: bool = False) -> list[dict]:
    sql = """SELECT id, text, subject, retriever_sha, opened_at
             FROM public.eval_question WHERE group_id = %s"""
    if unopened_only:
        sql += " AND opened_at IS NULL"
    sql += " ORDER BY id"
    return [
        {"id": i, "text": t, "subject": s, "retriever_sha": sha, "opened_at": o}
        for i, t, s, sha, o in conn.execute(sql, (group_id,)).fetchall()
    ]


def run_configurations(conn, group_id: str, question: dict, embedder,
                       configurations: dict[str, dict]) -> dict[str, list[str]]:
    """Retrieve for one question under every configuration, and store each.

    Called when judging opens, never before. `opened_at` is stamped here, so a
    question that has been retrieved for can be told from one that has not -
    and a question whose text changed after retrieval would be a different
    question, which the unique index already prevents.
    """
    from echo_memory.retrieval.query_memory import DEFAULT_TOP_K, query_memory

    sha = retriever_sha()
    out: dict[str, list[str]] = {}
    for name, kwargs in configurations.items():
        result = query_memory(
            conn, group_id, question["text"], DEFAULT_TOP_K, embedder, **kwargs
        )
        ids = [str(f["fact_id"]) for f in (result.get("facts") or [])]
        out[name] = ids
        conn.execute(
            """INSERT INTO public.eval_run (question_id, configuration, returned, retriever_sha)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (question_id, configuration)
               DO UPDATE SET returned = EXCLUDED.returned,
                             retriever_sha = EXCLUDED.retriever_sha,
                             ran_at = now()""",
            (question["id"], name, ids, sha),
        )
    conn.execute(
        "UPDATE public.eval_question SET opened_at = coalesce(opened_at, now()) WHERE id = %s",
        (question["id"],),
    )
    return out


def pool(conn, question_id: int, *, seed: int = SHUFFLE_SEED) -> list[str]:
    """Every fact any configuration returned for this question, shuffled.

    The union, not a concatenation: a fact several configurations found is one
    thing to judge, and judging it twice would weight it twice. Shuffled with a
    fixed seed so position says nothing about which configuration ranked it
    first, and so the same pool can be presented twice for an agreement check.

    Facts already judged are excluded, which makes judging resumable.
    """
    rows = conn.execute(
        "SELECT returned FROM public.eval_run WHERE question_id = %s ORDER BY configuration",
        (question_id,),
    ).fetchall()
    seen: list[str] = []
    for (returned,) in rows:
        for edge_id in returned or []:
            if edge_id not in seen:
                seen.append(edge_id)

    judged = {
        r[0] for r in conn.execute(
            "SELECT edge_id FROM public.eval_judgement WHERE question_id = %s",
            (question_id,),
        ).fetchall()
    }
    unjudged = [e for e in seen if e not in judged]
    random.Random(seed + question_id).shuffle(unjudged)
    return unjudged


def judge(conn, question_id: int, edge_id: str, relevant: bool, *,
          note: str | None = None, judged_by: str | None = None) -> None:
    """Record one relevance label for a (question, fact) pair.

    Not a (question, configuration) pair. A fact that answers a question
    answers it whoever surfaced it, so one label serves every configuration and
    the judge never has to be told - or be able to work out - which one did.
    """
    conn.execute(
        """INSERT INTO public.eval_judgement (question_id, edge_id, relevant, note, judged_by)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (question_id, edge_id)
           DO UPDATE SET relevant = EXCLUDED.relevant, note = EXCLUDED.note,
                         judged_by = EXCLUDED.judged_by, judged_at = now()""",
        (question_id, edge_id, relevant, note, judged_by),
    )


def coverage(conn, group_id: str) -> dict:
    """How much of the (question, fact) grid has actually been judged.

    Pooling bias is a property of how much was left unjudged, so it is a
    measurement rather than a disclaimer. At TREC scale the grid is
    unjudgeable and the caveat is permanent; this store holds a few hundred
    facts, which makes the whole grid reachable and the bias closable.
    """
    import json as _json

    from echo_memory.infra.db import GRAPH_NAME as GRAPH

    active = conn.execute(
        f"""SELECT count(*) FROM cypher('{GRAPH}', $$
            MATCH ()-[e:FACT]->() WHERE e.group_id = $g AND e.t_invalid IS NULL
            RETURN id(e) $$, %s) AS (i agtype)""",
        (_json.dumps({"g": group_id}),),
    ).fetchone()[0]
    n_questions = conn.execute(
        "SELECT count(*) FROM public.eval_question WHERE group_id = %s AND opened_at IS NOT NULL",
        (group_id,),
    ).fetchone()[0]
    judged = conn.execute(
        """SELECT count(*) FROM public.eval_judgement j
           JOIN public.eval_question q ON q.id = j.question_id
           WHERE q.group_id = %s""",
        (group_id,),
    ).fetchone()[0]
    possible = active * n_questions
    return {
        "active_facts": active,
        "questions": n_questions,
        "judged": judged,
        "possible": possible,
        "complete": possible > 0 and judged >= possible,
    }


def score(conn, group_id: str) -> dict:
    """Per-configuration metrics over the judged pool.

    precision@k  of the first k a configuration returned, how many were judged
                 relevant. The metric the old harness could not express,
                 because it marked exactly one fact correct.
    recall@k     over the POOLED relevant set for that question, never over the
                 store: a fact nothing returned was never judged.
    MRR          reciprocal rank of the first relevant fact.

    Questions with no relevant fact in the pool are excluded from recall and
    MRR and counted separately - they say something about the store, not about
    a configuration's ranking.
    """
    labels: dict[int, dict[str, bool]] = {}
    for qid, edge_id, relevant in conn.execute(
        """SELECT j.question_id, j.edge_id, j.relevant
           FROM public.eval_judgement j
           JOIN public.eval_question q ON q.id = j.question_id
           WHERE q.group_id = %s""",
        (group_id,),
    ).fetchall():
        labels.setdefault(qid, {})[edge_id] = relevant

    runs: dict[str, dict[int, list[str]]] = {}
    for qid, configuration, returned in conn.execute(
        """SELECT r.question_id, r.configuration, r.returned
           FROM public.eval_run r
           JOIN public.eval_question q ON q.id = r.question_id
           WHERE q.group_id = %s""",
        (group_id,),
    ).fetchall():
        runs.setdefault(configuration, {})[qid] = returned or []

    out: dict[str, dict] = {}
    for configuration, by_question in sorted(runs.items()):
        scored = 0
        no_relevant = 0
        p_at = {1: 0.0, 3: 0.0, 5: 0.0}
        r_at = {1: 0.0, 3: 0.0, 5: 0.0}
        rr_total = 0.0
        for qid, returned in by_question.items():
            judged = labels.get(qid) or {}
            if not judged:
                continue
            relevant_pool = {e for e, ok in judged.items() if ok}
            if not relevant_pool:
                no_relevant += 1
                continue
            scored += 1
            for k in p_at:
                top = returned[:k]
                hits = sum(1 for e in top if judged.get(e))
                p_at[k] += hits / k
                r_at[k] += hits / len(relevant_pool)
            rank = next(
                (i for i, e in enumerate(returned, start=1) if judged.get(e)), None
            )
            rr_total += (1.0 / rank) if rank else 0.0
        out[configuration] = {
            "questions": scored,
            "questions_with_no_relevant_fact": no_relevant,
            "precision_at": {k: (v / scored if scored else 0.0) for k, v in p_at.items()},
            "recall_at": {k: (v / scored if scored else 0.0) for k, v in r_at.items()},
            "mrr": rr_total / scored if scored else 0.0,
        }
    return out


def render(scores: dict, cover: dict | None = None) -> str:
    if not scores:
        return (
            "no judged questions yet.\n"
            "  echo-memory judge new \"<question>\"   records one, before anything is retrieved\n"
            "  echo-memory judge open                retrieves under every configuration\n"
            "  echo-memory judge pool                presents the shuffled union for labelling\n"
        )
    lines = [
        "",
        "Independent evaluation - questions written before retrieval, judged per fact",
        "",
        f"  {'configuration':<22}{'n':>5}{'P@1':>8}{'P@3':>8}{'R@3':>8}{'R@5':>8}{'MRR':>8}",
        "  " + "-" * 67,
    ]
    for name, s in scores.items():
        lines.append(
            f"  {name:<22}{s['questions']:>5}"
            f"{s['precision_at'][1]:>8.3f}{s['precision_at'][3]:>8.3f}"
            f"{s['recall_at'][3]:>8.3f}{s['recall_at'][5]:>8.3f}{s['mrr']:>8.3f}"
        )
    any_score = next(iter(scores.values()))
    if any_score["questions_with_no_relevant_fact"]:
        lines.append("")
        lines.append(
            f"  {any_score['questions_with_no_relevant_fact']} question(s) had no relevant "
            "fact anywhere in the pool and are excluded."
        )
    lines.append("")
    if cover and cover["complete"]:
        lines += [
            (f"Every ({cover['questions']} question x {cover['active_facts']} fact) pair "
             f"is judged - {cover['judged']} of {cover['possible']}."),
            "  Recall is therefore recall over the store, not over a pool. Nothing relevant",
            "  can be hiding in what no configuration returned, because there is no such",
            "  thing left unjudged.",
        ]
    elif cover:
        missing = cover["possible"] - cover["judged"]
        lines += [
            (f"Recall is over the POOLED relevant set: {missing} of "
             f"{cover['possible']} (question, fact) pairs"),
            "  are unjudged, so a relevant fact no configuration returned cannot count",
            "  against anything. Precision is unaffected and is the number to read first.",
        ]
    else:
        lines += [
            "Recall is over the POOLED relevant set, not the store: a fact no configuration",
            "  returned was never judged, so it cannot count against anything.",
        ]
    lines.append("")
    return "\n".join(lines)


# Characters of a fact shown when judging. Facts here run to 900; a judge
# deciding "does this help answer the question" needs the subject, not the
# whole record, and 119 full-length facts in a terminal is how a judging pass
# gets abandoned or rushed.
EXCERPT = 240


def export_pool(conn, group_id: str, *, only: int | None = None) -> str:
    """The whole judging pass as one editable file.

    Interactive prompting was the first design and it was the wrong surface:
    it needs a TTY, it cannot be paused and resumed inside a session, it shows
    one fact with no sense of how many remain, and it puts a judge under
    exactly the time pressure that produces labels nobody should build on. A
    file can be worked through in an editor, left half-done, diffed, reviewed
    by somebody else, and committed next to the result it produced.

    Still blind: facts appear in the pooled shuffled order with no
    configuration named and no rank shown.
    """
    import textwrap

    from echo_memory.retrieval.query_memory import _fetch_facts

    lines = [
        "# Relevance judging. Put y or n between the brackets; leave blank to skip.",
        "#",
        "#   y  this fact would help someone answer the question",
        "#   n  it would not - sharing a word with the question is not enough",
        "#",
        "# Several facts may be y for one question. If nothing here answers it,",
        "# mark them all n: that is a finding about the store, not a failed judgement.",
        "#",
        "# Facts are in pooled, shuffled order. Which configuration returned any of",
        "# them, and at what rank, is deliberately not shown.",
        "",
    ]
    total = 0
    for q in questions(conn, group_id):
        if not q["opened_at"] or (only is not None and q["id"] != only):
            continue
        ids = pool(conn, q["id"])
        if not ids:
            continue
        facts = _fetch_facts(conn, ids)
        lines += ["", "=" * 78, f"Q{q['id']}: {q['text']}", f"{len(ids)} fact(s)", ""]
        for edge_id in ids:
            fact = facts.get(edge_id)
            if not fact:
                continue
            text = (fact["fact"] or "").strip()
            if len(text) > EXCERPT:
                text = text[:EXCERPT].rsplit(" ", 1)[0] + " ..."
            wrapped = textwrap.wrap(text, width=70) or [""]
            lines.append(f"[ ] {edge_id}  {wrapped[0]}")
            lines += [f"    {' ' * len(edge_id)}  {w}" for w in wrapped[1:]]
            lines.append("")
            total += 1
    lines.append(f"# {total} fact(s) to judge.")
    return "\n".join(lines) + "\n"


def import_pool(conn, text: str, *, judged_by: str | None = None) -> dict:
    """Read a marked file back. Unmarked lines are left unjudged, not guessed."""
    import re

    pattern = re.compile(r"^\[\s*([yYnN]?)\s*\]\s+(\d+)\b")
    question_id: int | None = None
    counts = {"y": 0, "n": 0, "skipped": 0}
    for line in text.splitlines():
        heading = re.match(r"^Q(\d+):", line.strip())
        if heading:
            question_id = int(heading.group(1))
            continue
        match = pattern.match(line.strip())
        if not match or question_id is None:
            continue
        verdict, edge_id = match.group(1).lower(), match.group(2)
        if not verdict:
            counts["skipped"] += 1
            continue
        judge(conn, question_id, edge_id, verdict == "y", judged_by=judged_by)
        counts[verdict] += 1
    return counts
