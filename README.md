# Placement Studio

Describe a business in a sentence; get ranked publishers (and why the rest lost), 3–5 persona-tuned ads and a launch-ready campaign config, every number explained. Bad input gets an honest answer, not a campaign.

**Live:** https://byash010-placement-studio.hf.space (first load after 48 h idle takes a minute). The 15 samples are precomputed: instant, and they survive an OpenAI outage. A live run takes about 8–10 s.

```
cp .env.example .env          # add OPENAI_API_KEY
docker compose up --build     # one command: http://localhost:8000

uv sync; (cd web && npm install)                # local dev: install once
make dev-api; make dev-web                      # two terminals
uv run pytest -q; (cd web && npx vitest run)    # tests
```

## How it works

```
text ─▶ Understand (LLM) ─▶ Gate (LLM self-report) ─▶ Match (code) ─▶ Create (LLM) ─▶ Config (code)
```

**Numbers from code, words from the LLM.** Understand fills a brief restricted to the catalog's category vocabulary. The gate picks proceed, clarify (1–3 questions), out_of_scope or no_signal; after Match, a proceed with no publisher above the cut-off becomes weak_fit (closest 3, 20% test budget). Match scores publishers on four visible factors (category, audience, income, order value), personas on affinity, price and age. Create runs one call per persona in parallel; code rejects any number or claim word absent from the advertiser's text, with one retry. Models: gpt-5.4-mini for everything (≈4–5 s per live run, fractions of a cent); set OPENAI_MODEL_CREATIVE=gpt-5.5 for richer copy. The 15 precomputed samples were generated with gpt-5.5. Reasoning effort low. Every tunable is in `config/tuning.yaml`; every prompt is in `prompts/` ([index](prompts/README.md)).

## Campaign config, and why

| Field | Why a real system needs it |
|---|---|
| `objective`, `conversion_event` | Purchase vs subscription_start decides what the bidder optimises |
| `budget` (+ `unallocated_usd`, `test_budget`) | Capped at each publisher's reach; leftover shown, not dumped; weak fit gets a 20% test |
| `bid_strategy` | Target CPA = 35% × order value (× 2 for subscriptions): tied to unit economics |
| `targeting` | Ages, gender, US, interests, personas: who the ads were written for |
| `line_items` | Publisher, budget share (by fit, 10% floor) and the creative it serves |
| `frequency_cap` | 3 per 7 days; don't burn the audience |
| `guardrails` | Pause at 1.5× target CPA after 2,000 impressions: a bad launch stays cheap |
| `rationales`, `decision_trace` | One line per field plus gate and fit scores: any choice is auditable |

## Evals

120 labelled cases (given, paraphrases, ambiguity ladder, weak fit, out of scope, adversarial) split by group into 84 train / 36 held out ([details](evals/README.md)); `uv run python -m evals.run --split test`.

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

Image creatives, auth and saved campaigns, campaign editing, real auction/CPM modelling (a flat $12 CPM caps reach), an ad-policy engine. None changes how the core decisions get made; each is real work.

## With another week

A fresh eval batch as the clean check; learn weights and gate calibration from conversion data; an ad-policy layer; finer live-streaming stages and UI for the gate's signals.

**At scale:** LLMs for low-volume, ambiguous work (understanding advertisers, copy); small calibrated Laya-style models for high-volume typed decisions (per-impression matching, policy screening, catalog tagging): the LLM teaches, the small model serves. 20 → 10k publishers needs an embedding prefilter before scoring, plus caching, async workers, observability and cost per campaign.
