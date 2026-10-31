# Placement Studio

Describe a business in a sentence; get ranked publishers (and why the rest lost), 3–5 persona-tuned ads to regenerate and approve, then a launch-ready campaign config with every number explained. Bad input gets an honest answer, not a campaign.

**Live:** https://byash010-placement-studio.hf.space (cold start ≈1 min). The 15 samples are precomputed (`make samples`), so they load instantly; during an OpenAI outage steps ① and ③ still work (② serves cached ads, but Regenerate is live).

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

Stages are stateless: each request carries back what the last returned, signed by ① (HMAC, `STAGE_SECRET`); ② and ③ refuse changes (403). Live calls are rate-limited; ③ is free.

**Numbers from code, words from the LLM.** Understand fills a brief in the catalog's vocabulary. The gate picks proceed, clarify, out_of_scope or no_signal; a proceed with no publisher above the cut-off becomes weak_fit. Match scores publishers on four visible factors (category, audience, income, order value) and personas on affinity, price and age. Create writes one ad per persona in parallel from a [copywriting playbook](prompts/copywriting_playbook.md); code checks each ad (invented facts, length, generic copy, parroting), retries once, then flags it ([details](prompts/README.md)). gpt-5.4-mini reads briefs, gpt-5.5 writes ads (≈3¢ per campaign). Tunables: `config/tuning.yaml`; prompts: `prompts/`.

## Campaign config, and why

| Field | Why a real system needs it |
|---|---|
| `objective`, `conversion_event` | Purchase vs subscription_start decides what the bidder optimises |
| `budget` | Recommended = Σ per publisher of min(reach cap, target CPA × 50 conversions), rounded to $500. Weak fit: a test of min(20% of that, $3,000). Your budget wins (`source: user`). Pacing by fit and tier |
| `bid_strategy` | Target CPA = 35% × order value (× 2 for subscriptions): tied to unit economics |
| `targeting` | Ages, gender, US, interests, personas the ads were written for |
| `line_items` | Publisher, budget share (by fit, 10% floor, capped at reach) and its ad; reused ads are named |
| `frequency_cap` | By price tier (value 5/7 days … luxury 2/21); a weak-fit test shows one fewer within 14 days |
| `guardrails` | Pause at 1.5× target CPA after 2,000 impressions: a bad launch stays cheap |
| `rationales`, `decision_trace` | One line per field, plus gate and fit scores |

## Evals

121 labelled cases split by group into 85 train / 36 held out ([details](evals/README.md)). `uv run python -m evals.run --split test` runs all three stages per case.

- Train **85/85**; held out **35/36 = 97.2%**; the 15 given examples **15/15** (2026-10-31; evals write ads with gpt-5.4-mini to save cost).
- 1 invariant failure held out: an ad kept an unsourced "3" after retry (flagged, not hidden).
- Caveats: 3rd held-out run, post-hoc (examples once copied eval wording; rewritten again today); noise ±1 case. A Laya gate scored lower.

## Hard vs easy

Easy: calling an LLM, rendering a UI. Hard:

- **Knowing when not to build a campaign.** A calibrated gate and five honest outcomes.
- **Explainable, stable matching.** Code over a fixed vocabulary; every score splits into visible parts.
- **Factual creatives.** The facts check is code, not a plea to the model.
- **Honest evals.** Group splits, train-only calibration, catching contamination.

## What I cut, and why

Image creatives, auth and saved campaigns, editing config beyond the budget, real auction modelling (a flat $12 CPM caps reach), an ad-policy engine: each is real work that doesn't change the core decisions.

## With another week, and at scale

A fresh eval batch; learn weights and gate calibration from conversion data; an ad-policy layer. At scale: LLMs for low-volume ambiguous work, small calibrated models for high-volume typed decisions, and an embedding prefilter before scoring 10k publishers.
