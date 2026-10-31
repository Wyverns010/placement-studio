# Placement Studio

Describe a business in a sentence; get ranked publishers (and why the rest lost), then 3–5 persona-tuned ads you can regenerate and approve, then a launch-ready campaign config with a recommended budget, every number explained. Bad input gets an honest answer, not a campaign.

**Live:** https://byash010-placement-studio.hf.space (first load after 48 h idle takes a minute). The 15 samples are precomputed stage by stage with the default models (`make samples`): instant, and they survive an OpenAI outage.

```
cp .env.example .env          # add OPENAI_API_KEY
docker compose up --build     # one command: http://localhost:8000

uv sync; (cd web && npm install)                # local dev: install once
make dev-api; make dev-web                      # two terminals
uv run pytest -q; (cd web && npx vitest run)    # tests
```

## How it works

```
① text ─▶ Understand (LLM) ─▶ Gate ─▶ Match (code)     POST /api/campaign, GET /api/campaign/stream
② Create (LLM): one ad per persona; Regenerate one     POST /api/creatives, /api/creatives/regenerate
③ Config (code) at the recommended or your budget      POST /api/config
```

Three stages the user steps through, stateless: each request carries back what the last one returned. Stage ① signs its result (`stage_token`, HMAC-SHA256 keyed by `STAGE_SECRET`; unset means a random key per process, so tokens die on restart) and ② and ③ refuse anything changed (403), then re-validate it (request models in `app/api.py`). Live calls count against the rate limit (`config/tuning.yaml`: 20 runs per client per 10 min, 200/h overall; ① costs 1, writing ads 2, a regenerate 1); ③ is free.

**Numbers from code, words from the LLM.** Understand fills a brief restricted to the catalog's category vocabulary. The gate picks proceed, clarify (1–3 questions), out_of_scope or no_signal; after Match, a proceed with no publisher above the cut-off becomes weak_fit (closest 3, a test budget). Match scores publishers on four visible factors (category, audience, income, order value), personas on affinity, price and age. Create runs one call per persona in parallel, following a written [copywriting playbook](prompts/copywriting_playbook.md) (persona motivation first, one true detail, the publisher's context); code checks every ad for invented numbers or claim words, over-long fields, generic copy (age ranges, "for women", "under $N", filler) unless the advertiser wrote it, and parroting (6+ words or a whole sentence copied from the advertiser); a failing ad is retried once, then flagged. Regenerate rewrites one ad, optionally steered by a note that is passed as data. Models: gpt-5.4-mini reads briefs and writes questions; gpt-5.5 writes ads (≈3¢ per full campaign); override with OPENAI_MODEL_FAST / OPENAI_MODEL_CREATIVE. Reasoning effort low. Every tunable is in `config/tuning.yaml`; every prompt is in `prompts/` ([index](prompts/README.md)).

## Campaign config, and why

| Field | Why a real system needs it |
|---|---|
| `objective`, `conversion_event` | Purchase vs subscription_start decides what the bidder optimises |
| `budget` (`monthly_usd`, `recommended_usd`, `source`, `pacing`, `unallocated_usd`, `test_budget`) | Recommended = Σ over publishers of min(reach cap, target CPA × 50 conversions: enough to optimise a CPA bid), rounded to $500 and clamped; weak fit recommends 20% of that as a test. Your budget wins (`source: user`). Pacing: weak fit `front_loaded`; premium/luxury `even`; value/mid `accelerated` only below the recommendation |
| `bid_strategy` | Target CPA = 35% × order value (× 2 for subscriptions): tied to unit economics |
| `targeting` | Ages, gender, US, interests, personas: who the ads were written for |
| `line_items` | Publisher, budget share (by fit, 10% floor, capped at reach) and the creative it serves |
| `frequency_cap` | By price tier: value 5/7 days, mid 4/7, premium 3/14, luxury 2/21, unknown 3/7; +1 for a subscription, −1 for a weak-fit test |
| `guardrails` | Pause at 1.5× target CPA after 2,000 impressions: a bad launch stays cheap |
| `rationales`, `decision_trace` | One line per field plus gate and fit scores: any choice is auditable |

## Evals

120 labelled cases (given, paraphrases, ambiguity ladder, weak fit, out of scope, adversarial) split by group into 84 train / 36 held out ([details](evals/README.md)); `uv run python -m evals.run --split test` runs all three stages per case (`run_full`) and checks invariants on the full chain.

- Train **84/84**; held out **34/36 = 94.4%** (2026-10-31 run); the 15 given examples **15/15**; 0 invariant failures.
- Noise is about ±1 case per split. Held-out figures are post-hoc: the first run was contaminated (prompt examples copied eval wording) and I rewrote them after seeing test texts, so a fresh batch is the clean check.
- Laya gate (`GATE_IMPL=laya`), calibrated on train only: **30/36** held out vs 34/36, plus ~2 GB RAM and 0.3–0.5 s per request. LLM gate stays default.

## Hard vs easy

Easy: calling an LLM, rendering a UI. Hard:

- **Knowing when not to build a campaign.** A calibrated gate and five honest outcomes; below it, no launchable config exists.
- **Explainable, stable matching.** Code over a fixed vocabulary, so every score splits into visible parts.
- **Factual creatives.** The facts check is code, not a plea to the model.
- **Evaluating without fooling yourself.** Group splits, train-only calibration, catching the contamination above.

## What I cut, and why

Image creatives, auth and saved campaigns, editing config fields beyond the budget, real auction/CPM modelling (a flat $12 CPM caps reach), an ad-policy engine. None changes how the core decisions get made; each is real work.

## With another week

A fresh eval batch as the clean check; learn weights, gate calibration and conversions-per-line-item from conversion data; an ad-policy layer; UI for the gate's signals.

**At scale:** LLMs for low-volume, ambiguous work (understanding advertisers, copy); small calibrated Laya-style models for high-volume typed decisions (per-impression matching, policy screening, catalog tagging): the LLM teaches, the small model serves. 20 → 10k publishers needs an embedding prefilter before scoring, plus caching, async workers, observability and cost per campaign.
