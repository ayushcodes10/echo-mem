# Benchmarks

Every number here was taken on a stated date with the command that reproduces
it. Where a number is unflattering it is still here, because a benchmark you
only publish when it wins is marketing.

## What is measured, and what is not

LoCoMo and LongMemEval are published as **QA accuracy**: a model reads what
memory returned, writes an answer, and a second model judges it against a gold
answer. Those are the numbers people quote, including the state of the art
claims made by hosted memory products.

Echo Memory's harnesses measure **retrieval**: whether the turn holding the
answer came back at all. No model is called anywhere in either script.

Retrieval is a **ceiling on** QA accuracy, not a substitute for it. A system
that never surfaces the evidence cannot answer the question, so a low retrieval
number is decisive and a high one is necessary rather than sufficient. These
results are not comparable to a published QA accuracy figure and should never
be quoted as though they were.

There is a second, sharper caveat specific to this design. Both harnesses feed
**raw, unfiltered dialogue turns**, one fact per turn. That deliberately skips
the step Echo Memory pushes to the calling agent, which is deciding what in a
conversation was worth remembering at all. So these numbers describe the store
with its extraction step removed, which is this architecture's worst case. See
[WRITE-COST.md](WRITE-COST.md) for why that step lives where it does.

## LoCoMo, 2026-09-17

Ten conversations, 5,882 dialogue turns, 1,982 questions whose gold answers
cite the exact turns supporting them.

```bash
curl -sLO https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
python scripts/locomo-bench.py locomo10.json
```

| Category | n | recall@1 | recall@10 | recall@30 | hit@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|
| **overall** | **1,982** | **0.324** | **0.601** | **0.708** | **0.658** | **0.460** |
| temporal | 321 | 0.439 | 0.691 | 0.794 | 0.717 | 0.556 |
| single hop | 841 | 0.383 | 0.680 | 0.773 | 0.697 | 0.498 |
| adversarial | 446 | 0.308 | 0.584 | 0.697 | 0.594 | 0.401 |
| multi hop | 282 | 0.099 | 0.386 | 0.530 | 0.649 | 0.391 |
| open domain | 92 | 0.139 | 0.310 | 0.415 | 0.435 | 0.263 |

`recall@k` is the share of a question's cited turns returned in the top k.

**Multi hop is the worst row and it is the expected one.** recall@1 of 0.099
says that when an answer needs two turns joined, ranking the single best fact
is nearly useless. This is the case v1b's multi hop retrieval exists for, and
the number to beat now exists before the feature does, which is the same
posture as the 187 question MRR 0.212 figure in the README.

**Open domain is low and mostly should be.** Those questions need world
knowledge that is not in the transcript, so no retrieval over the transcript
can supply it. It is reported rather than excluded because excluding a category
because it is hard is how benchmark tables become useless.

**Temporal being the strongest row is a consequence of a design decision, not a
surprise.** Each fact records the date the turn was spoken, in the fact text, so
"when did she say that" has something to match against.

## LongMemEval S

500 questions, each with its own haystack of roughly 50 chat sessions, 246,930
turns in total.

```bash
curl -sLo longmemeval_s.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval/resolve/main/longmemeval_s
python scripts/longmemeval-bench.py longmemeval_s.json
```

Two recalls are reported because the benchmark supports both and they answer
different questions. `session@k` asks whether the right conversation surfaced,
which is what a reader would then have to read. `turn@k` asks whether the
specific line flagged `has_answer` surfaced, which is what retrieval working
should mean for a store that returns facts rather than documents.

## Context cost as the store grows

`eval --context` reports one number, and a number without its denominator is
easy to read wrongly in both directions. `eval --context --sweep` measures the
same thing at several corpus sizes, by building real sub scopes from a prefix
of the store's own facts and querying each one.

On this author's store, 2026-09-17:

```
    facts    inject   recall   hit@10   saving
  --------------------------------------------
       32     4,531    1,108    0.900    75.5%
       65     9,371    1,168    0.887    87.5%
      130    21,288    1,431    0.911    93.3%
      261    42,633    1,522    0.946    96.4%
```

Across 8x of corpus growth the cost of injecting everything rose 9x, while what
a recall returned moved **+37%**. The recall cost is bounded, not fixed, and the
sweep prints the drift rather than assuming it away: `top_k` limits how many
facts come back but not how long they are.

`hit@10` is printed in every row deliberately. A saving is only worth having if
the answer is still in what came back, and a configuration that returned nothing
would score a perfect 100%.

## What a write costs as the store grows

Found while ingesting LongMemEval, by noticing that throughput fell from 28
writes a second to 8 over one run and then checking whether that was the
machine or the store. It was the store: an empty database on the same machine
at the same moment still ran at 28/s.

| Store size | Before | After |
|---|---:|---:|
| 1,057 nodes | 29ms | 22ms |
| 24,054 nodes | 129ms | 45ms |

Two defects, both the same shape. A neighbourhood lookup and an entity lookup
each went through Cypher, where `MATCH ... WHERE id(x) = $id` cannot use an
index, because AGE expands the match and filters afterwards. Each therefore
scanned the whole graph on every write: every scope, and in a hosted deployment
every tenant. Read off the tables directly they are index lookups, and one of
them reaches an index that migration 0016 had already built for it.

The remaining growth, roughly 2x across that range, is the vector index getting
larger as it gains rows. That one is real rather than a defect, and it is the
number to beat next.

## Reproducing any of it

Point every script at a scratch database. They write real facts through the
real code path, so anything they touch is indistinguishable from ordinary
memory afterwards.

```bash
echo-memory eval                   # retrieval quality against your own store
echo-memory eval --context         # what a recall costs against injecting everything
echo-memory eval --context --sweep # the same, as a curve across corpus size
echo-memory calibrate              # is entity resolution trustworthy on your data
echo-memory benchmark              # write, query and digest latency
```

The most useful contribution to this repository is a measurement that disagrees
with one of these.
