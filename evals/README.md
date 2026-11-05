# Evals

121 labelled advertiser inputs. They set the gate thresholds and the scoring weights, and every full
run also checks the structural invariants (`invariants.py`) on each campaign it builds.

## The cases (`cases.jsonl`)

| Group | Cases | Labels |
|---|---|---|
| The 15 given examples (`given-*`) | 15 | the brief's expected outcomes; #9 accepts proceed or weak_fit |
| Paraphrases of the 15 (`para-*`) | 15 | same as the original |
| Clear advertisers, 3 per catalog category (`clear-*`) | 30 | proceed + 1 must publisher |
| Ambiguity ladder: 6 businesses × clear / partial / vague / empty (`ladder-*`) | 24 | proceed / proceed / clarify / no_signal |
| Weak fit: luxury, outdoor, auto, baby gear, furniture, e-bikes (`weak-*`) | 10 | weak_fit |
| Out of scope: B2B, local services, job ad, charity, political (`oos-*`) | 10 | out_of_scope |
| Sensitive: vape, betting, holsters, CBD (`sens-*`) | 4 | any outcome but no_signal |
| Adversarial: injections, multi-product, typos, 1,600 chars, Spanish, gibberish, URL (`adv-*`) | 12 | see `note` |

A named product proceeds even without a price or buyer; a domain hint with no product clarifies; no
business content is no_signal. Borderline cases accept two outcomes and say why in `note`.
`must_publishers` / `must_not_publishers` name a publisher a media buyer would insist on / never
use; `must_personas` / `must_not_personas` (79 cases) do the same for shoppers. `split` is by
`group`, so a paraphrase sits with its original: 85 train, 36 held out.

## How to run

```
uv run python -m evals.run --stage1 --split all   # outcomes, publishers, personas (step 1 only)
uv run python -m evals.run --split train          # all four steps, plus the invariants
uv run python -m evals.calibrate                  # best gate thresholds on train (prints, never writes)
```

LLM answers are cached in `.cache/llm`, so a re-run is free; `--no-cache` calls the model live.
Each run writes `last_run.json`.

## Current numbers (step 1, 2026-11-05)

| | Outcomes | Must publisher hit | Must-not avoided | Right personas | Wrong personas avoided |
|---|---|---|---|---|---|
| Train | **84/85** | 96% | 100% | 96% | 100% |
| Held out | **34/36** | 100% | 100% | 100% | 100% |
| The 15 given examples | **15/15** | 89% | 100% | 92% | 100% |

`calibrate` keeps today's thresholds (proceed 0.70, no_signal 0.30, business 0.50; 98.8% on train).
Run-to-run noise is about ±1 case per split: an LLM answer not in the cache is re-sampled. The
held-out split has been looked at several times since it was written, so its numbers are post-hoc.

## Known misses

- `ladder-throws-empty` ("Our company.") → clarify, not no_signal: the model calls it business
  content with confidence 0.12.
- `oos-lawyer`, `oos-shelter` → weak_fit / proceed: the brief reads them as shoppable. The gate
  only refuses what the brief marks `business` or `not_shoppable`.
- `given-09` (refill cleaning concentrate): Pantrygood, the must publisher, is sometimes missing.

## Experiments (code removed, results kept here)

| Tried | Result | Kept? |
|---|---|---|
| Tuning weights and thresholds on train | 61/84 → 84/84 train | yes, in `app/models/tuning.py` |
| A Laya encoder gate (4 typed questions) instead of the LLM's own read | 30/36 held out vs 34/36; +0.3–0.5 s and ~2 GB per process | no |
| A graph matcher for publishers | tied the formula on every case | no |
| Agents (OpenAI Agents SDK) per step | same picks as code for steps 1, 2, 4; a judge preferred their ads 67% of the time | no: plain LLM calls are simpler; the Copywriter → Critic → one revision loop is kept |
