# Evals

A labelled set of 120 advertiser inputs that drives the gate thresholds, the scoring weights and the
Understand prompt, plus structural invariants checked on every case.

## What the set covers (`cases.jsonl`)

| Bucket | Cases | Labels |
|---|---|---|
| The 15 given examples (`given-*`) | 15 | spec table; #9 accepts proceed or weak_fit |
| Paraphrases of the 15 (`para-*`, same `group`) | 15 | same as the original |
| Clear advertisers, 3 per catalog category, $2.50 to $180 (`clear-*`) | 30 | proceed + 1 must publisher |
| Ambiguity ladder: 6 businesses x clear / partial / vague / empty (`ladder-*`) | 24 | proceed / proceed / clarify / no_signal |
| Weak fit: luxury, outdoor, auto, baby gear, furniture, e-bikes (`weak-*`) | 10 | weak_fit |
| Out of scope: B2B, local services, job ad, charity, political, nonprofit (`oos-*`) | 10 | out_of_scope |
| Sensitive: vape, betting, holsters, CBD (`sens-*`) | 4 | robustness only, any outcome but no_signal |
| Adversarial: 3 injections, multi-product, typos and emoji, 1,600 chars, Spanish, gibberish, URL, competitor name (`adv-*`) | 12 | see `note` |

Labelling rules: a named product proceeds even without a price or buyer (spec #11); a domain or
audience hint with no product clarifies (#5, #8); no business content is no_signal (#15). Borderline
cases list two acceptable outcomes and say why in `note`. `must_publishers` names one publisher a
media buyer would insist on; `must_not_publishers` names a clear mismatch. Injection cases forbid
Swiftcart (`pub_001`). Cases drafted with `evals/generate.py` (it writes `candidates.jsonl` for
review, never `cases.jsonl`) were hand-edited and carry `origin: "llm-edited"`; everything except
the 15 given examples is `synthetic: true`.

`split` is `split_for(group)` (sha1, 70/30), so a paraphrase always sits with its original. Ladder
rungs use one group each. The result is 84 train and 36 test cases.

## How to run

```
uv run python -m evals.run --split train            # accuracy, confusion, invariants -> last_run.json
uv run python -m evals.run --only given-05,para-05  # targeted re-check
uv run python -m evals.calibrate --split train --dry-run
uv sync --group laya                                 # optional Laya gate (torch + 1.6 GB checkpoint)
uv run --group laya python -m evals.run --gate laya --split train --concurrency 1
uv run python -m evals.calibrate --gate laya --split train   # writes gate.laya only
```

Each run also writes `last_run_<gate>_<split>.json`. `calibrate --gate laya` refuses records from
the other gate.

LLM calls are cached in `.cache/llm`, so re-runs are free; `--no-cache` forces live calls. The runner
truncates input to `input.max_chars` like the API, and reports the creative retry rate (personas
re-asked after a facts or length violation) and latency p50/p90.

## Latest numbers (2026-10-30, gpt-5.4-mini for Understand/clarify, gpt-5.5 for creatives, effort low)

| | Accuracy | Invariant failures | Must hit | Must-not avoided |
|---|---|---|---|---|
| Train baseline (before tuning) | 61/84 = 72.6% | 0 | 90% | 100% |
| Train after tuning, examples de-contaminated | 83/84 = 98.8% | 0 | 94% | 100% |
| **Held-out test (official, re-run)** | **35/36 = 97.2%** | **0** | 100% | 100% |
| Held-out test, first run (contaminated, superseded) | 34/36 = 94.4% | 0 | 100% | 100% |
| **The 15 given examples** | **15/15** (13 train, 2 test) | 0 | | |

**The first held-out run was contaminated.** Several examples in `prompts/understand.md` copied
eval wording: "just make a campaign" (test case `ladder-protein-empty`), "Glossier", "$2.50 a can,
12-packs", "we're in the self-care space", "we help people feel better" (given #5, which is in the
test split), "idk just try it", "$1,200 handbag", plumber/dentist/lawyer, and others. Every example
was replaced with wording that appears in no case text; the rules stayed the same. Train and test
were then re-run once each. The official held-out figure is the re-run: **35/36**. The first run
scored 34/36. Before the fix, train was 84/84. The one case it lost, `clear-beverages-1` ("$2.50 a
can, sold in 12-packs"), had only passed because the prompt quoted its own wording. It was left as
a known miss rather than re-tuned.

**Caveat:** the prompt was revised after viewing held-out case texts, in order to remove the
copied wording. That makes 35/36 a post-hoc held-out figure, not a pristine one. The next batch of
fresh cases, written after this prompt, will be the clean check. Both numbers are kept above.

`aov_below_log2_scale: 5` was fit on the train split only. Values 4, 5 and 6 gave identical train
results in the offline simulation.

Targets: at least 85% held out, 15/15 given, 0 invariant failures. All met. Creative retry rate: 1
persona in about 780 across the five post-tuning runs (about 0.1%), with no residual violations.
Latency at concurrency 8, uncached Understand: p50 5.6s, p90 7.1s per case.

## Gate comparison: LLM self-report vs Laya (2026-10-31)

`LayaGate` asks the open-source Laya encoder (`convaiinnovations/laya`, `typed-decisions`
checkpoint, Apache-2.0) four typed questions from `prompts/laya_questions.yaml`. Both gates see the
same Understand briefs (same LLM cache), so only the gate differs. Each gate was calibrated on train
only: the LLM gate keeps its earlier thresholds (`calibrate --dry-run` found no better values), and
Laya got its own `gate.laya` block (proceed 0.45, no_signal 0.40, business 0.65; before
calibration, on the LLM gate's thresholds, Laya scored 28/84). Question wording was iterated on
train only (82% to 87% in the offline fit). Held out was then run **once per gate**.

| | LLM self-report gate | Laya gate |
|---|---|---|
| Train, after own calibration | **84/84 = 100%** | 73/84 = 86.9% |
| **Held-out test, single run** | **34/36 = 94.4%** | 30/36 = 83.3% |
| The 15 given examples | 15/15 | 15/15 |
| Recall, test: proceed / weak_fit / clarify / out_of_scope / no_signal | 17/17, 7/7, 3/4, 3/3, 4/5 | 16/17, 4/7, 4/4, 3/3, 3/5 |
| Recall, train (same order) | 55/55, 7/7, 7/7, 9/9, 6/6 | 52/55, 6/7, 4/7, 6/9, 5/6 |
| Gate latency per case | about 0 ms (reads the brief the Understand call already returned) | 278 ms on Apple MPS, about 470 ms on CPU (4 threads) |
| Extra cost to run | none | +1.6 GB checkpoint, about 1.9 GB RSS on CPU, torch in the image |

Recall here groups cases by their first expected label and counts a hit when the outcome is any
accepted label. This LLM held-out run is 34/36, not the 35/36 above, because some Understand calls
were not cached and were re-sampled. It missed `ladder-throws-empty` (clarify) and
`ladder-protein-vague` (no_signal).

**Laya loses, by about 11 points held out.** The reasons are visible in the raw probabilities:

- They are compressed. `has_content` runs 0.46 to 0.74 for clear advertisers and 0.26 to 0.59 for
  no-signal inputs, so no single threshold separates them. "Please help us advertise." scores 0.59.
- The four buyer options rarely leave 0.15 to 0.30 each, so `business + not_shoppable` sits near
  0.45 for ordinary consumer brands and only reaches 0.56 to 0.83 for real out-of-scope cases.
- Weak-fit products outside the catalog (car exhaust, rings, golf) get a category that disagrees
  with the brief (`other`, or `apparel` for golf). The clarity penalty applies on top of an already
  low `product_identifiable` (0.43 to 0.50), and they come back clarify instead of weak_fit. That is
  3 of the 6 held-out misses. These are observations only; nothing was re-tuned on test.
- The 11-way category question uses a temperature that the checkpoint flags as invalid
  ("treat confidence as uncalibrated"). Only its argmax is used, but it is a warning sign.

The LLM gate wins because its signals come from a model that has already read the text closely
enough to fill in the whole brief. Laya is a small encoder answering from the text alone.

**Recommendation: keep the LLM gate as the production default (`GATE_IMPL=llm`).** Laya is
calibrated and inspectable, but on this set it is less accurate on both splits. It adds about 0.3
to 0.5 s per request and about 2 GB of memory, and it saves no LLM call, because Understand still
has to run to drive matching. A hybrid (for example, Laya as a cheap no_signal pre-filter before
the LLM call) is not supported by these numbers: Laya's no_signal recall is 3/5 held out. Revisit
if a fine-tuned or larger Laya checkpoint becomes available. `GATE_IMPL=laya` stays available for
side-by-side checks.

## Known misses

- Held out: `ladder-throws-empty` ("Our company.") came back clarify. The model marked it as
  business content with confidence 0.14. A likely fix is to treat `self_confidence < 0.2` as
  no_signal in the gate. It was not applied, because that would mean tuning on the test split.
  `ladder-protein-vague`, which missed on the first contaminated run, passed on the re-run.
- Train: `clear-beverages-1`. The model kept the $2.50 per-can price instead of the 12-pack
  price, so Pop & Sip's AOV fit fails and the case comes back weak_fit.
- `given-09` / `para-09` (refill cleaning concentrate): Swiftcart (household) is recommended, but
  Pantrygood, the must publisher, is not always in the list.
- With a female buyer and a mid price tier, Marlowe & Co. and Linden Park (women aged 45 to 70)
  can fill the last slots for women's supplements. Audience and income match, but the category
  does not.
