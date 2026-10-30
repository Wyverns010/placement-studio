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
```

LLM calls are cached in `.cache/llm`, so re-runs are free; `--no-cache` forces live calls. The runner
truncates input to `input.max_chars` like the API, and reports the creative retry rate (personas
re-asked after a facts or length violation) and latency p50/p90.

## Latest numbers (2026-10-30, gpt-5.4-mini for Understand/clarify, gpt-5.5 for creatives, effort low)

| | Accuracy | Invariant failures | Must hit | Must-not avoided |
|---|---|---|---|---|
| Train baseline (before tuning) | 61/84 = 72.6% | 0 | 90% | 100% |
| Train after tuning (uncached re-run) | 84/84 = 100% | 0 | 94% | 100% |
| **Held-out test (single run)** | **34/36 = 94.4%** | **0** | 100% | 100% |
| **The 15 given examples** | **15/15** (13 train, 2 test) | 0 | | |

Targets: at least 85% held out, 15/15 given, 0 invariant failures. All met. Creative retry rate: 1
persona in about 290 across the uncached train run and the test run (about 0.3%), with no residual
violations. Latency at concurrency 8, uncached: p50 5.7s, p90 6.7s per case.

## Known misses

- Held out, both at the clarify / no_signal edge: `ladder-throws-empty` ("Our company.") came back
  clarify (the model marked it as business content with confidence 0.14), and `ladder-protein-vague`
  ("Helping people hit their goals.") came back no_signal. A likely fix is to treat
  `self_confidence < 0.2` as no_signal in the gate. It was not applied, because that would mean
  tuning on the test split.
- `given-09` / `para-09` (refill cleaning concentrate): Swiftcart (household) is recommended, but
  Pantrygood, the must publisher, is not always in the list.
- With a female buyer and a mid price tier, Marlowe & Co. and Linden Park (women aged 45 to 70)
  can fill the last slots for women's supplements. Audience and income match, but the category
  does not.
