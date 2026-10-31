# Placement Studio

Describe a business in a sentence; get ranked publishers (and why the rest lost), 3–5 persona-tuned ads to regenerate and approve, then a launch-ready campaign config with every number explained. Bad input gets an honest answer.

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
① Understand ─▶ Gate ─▶ Match; Strategist agent if steered   POST /api/campaign, GET /api/campaign/stream
② Copywriter + Critic agents: one ad per persona; Regenerate   POST /api/creatives, /api/creatives/regenerate
③ Config (code); a Media planner agent only for a steer        POST /api/config
```

Stages are stateless: each request carries back what the last returned, signed by ① (HMAC, `STAGE_SECRET`); ② and ③ refuse changes (403). Live calls are rate-limited; ③ is free unless steered.

**Numbers from code, words from the LLM.** Understand fills a brief in the catalog's vocabulary. The gate picks proceed (weak_fit if nothing clears the cut-off), clarify, out_of_scope or no_signal. Match scores publishers on four visible factors and personas on three. Ads follow a [copywriting playbook](prompts/copywriting_playbook.md); code checks each (invented facts, length, generic copy, parroting) and flags what still fails ([details](prompts/README.md)).

**Step agents** ([OpenAI Agents SDK](app/stepagents/)): each step takes an optional steer ("skip pet stores", "under $5k"). The agent proposes, code disposes: agents pick tool inputs (tools wrap the existing functions) and write words; code assembles every result, the gate is final, a steer can't leave fewer than two publishers, and each step returns `agent_trace` and `agent_notes`. The Critic runs code's checks, at most 2 rounds per ad. Any error, timeout or cost cap (≈25–30¢ per session worst case; `config/tuning.yaml`) falls back to plain code (`mode: "fallback"`); unsteered samples stay cached. gpt-5.5 writes; gpt-5.4-mini does the rest.

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

- Code pipeline: train **85/85**; held out **35/36 = 97.2%**; the 15 given examples **15/15** (2026-10-31; ads by gpt-5.4-mini).
- [Agents vs code](evals/AGENT_COMPARISON.md): ① and ③ agent only when steered; ② see the doc.
- [Graph vs formula](evals/GRAPH_COMPARISON.md): ties on every label; formula stays.
- 1 invariant failure held out: an unsourced "3" kept after retry (flagged, not hidden).
- Caveats: 3rd held-out run, post-hoc; noise ±1 case.

## Hard vs easy

Easy: calling an LLM. Hard: knowing when not to build a campaign (a calibrated gate, five honest outcomes); explainable, stable matching (every score splits into visible parts); factual creatives (the facts check is code, not a plea); honest evals (group splits, train-only calibration).

## What I cut, and why

Image creatives, auth and saved campaigns, real auction modelling (a flat $12 CPM caps reach), an ad-policy engine: none changes the core decisions.

## With another week, and at scale

A fresh eval batch; learn weights and gate calibration from conversion data; an ad-policy layer. At scale: LLMs for ambiguous low-volume work, small calibrated models for typed decisions, an embedding prefilter before scoring 10k publishers.
