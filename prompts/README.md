# Prompts

Every prompt the app sends lives here and is read from disk at runtime (`app/prompts.py`
`render(name, **slots)`, which is `str.format_map`: a missing slot raises `KeyError`, and literal
braces are doubled). The advertiser's raw text is sent only in the user message, inside
`<advertiser_text>` tags (`wrap_advertiser_text`), and each prompt treats it as data. Fields that
Understand extracted from it (`product`, `facts`, `unknowns`) are rendered into the creative and
clarify system prompts as listed data; in stages 2 and 3 they come back from the client, so the API
only accepts them with a valid `stage_token` and within size caps. A Regenerate note goes in the user
message inside `<user_note>` tags (`wrap_user_note`) and the ad being replaced inside `<current_ad>`
(`wrap_current_ad`): both are data; the note can steer tone or angle but never adds facts (the facts
check still reads only the advertiser's text).

| File | Stage (caller) | Model | Slots | Output |
|---|---|---|---|---|
| `understand.md` | Stage 1 Understand (`app/understand.py`) | `OPENAI_MODEL_FAST` (gpt-5.4-mini) | `category_vocab` (one line per publisher category with its subcategories, so "treats" reads as pet treats), `interest_vocab` (persona affinity terms), `conflict_vocab` | Structured brief; categories and conflicts are enums built from the catalog, so the model cannot invent a category |
| `clarify.md` | Stage 1, clarify outcome only (`app/create.py` `clarify_questions`) | `OPENAI_MODEL_FAST` (gpt-5.4-mini) | `product`, `facts`, `unknowns`, `categories` | 1 to 3 questions, 2 to 5 tap-able options each (`clarify` caps in tuning) |
| `creative.md` | Stage 2 Create (`app/create.py` `_call_one`): one call per persona, in parallel (`write_creatives`), or one call to rewrite an ad (`rewrite_creative`, Regenerate) | `OPENAI_MODEL_CREATIVE` (gpt-5.5) | `product`, `facts`, `headline_max`, `body_max`, `cta_max`, `personas` (this persona's block), `publisher` (publisher context: category, audience ages/gender/income, AOV, notes), `others` (the other personas' angles), `playbook` (rendered `copywriting_playbook.md`) | One ad (headline, body, CTA, why). Code (`app/copycheck.py` `ad_problems`) rejects numbers, claim words or lengths not allowed generic copy (age ranges, "for women"-style targeting echoes, "under $N", `creative.banned_phrases`) the advertiser didn't write, and parroting (`creative.parrot_ngram` = 6 consecutive advertiser words, or a whole advertiser sentence of 4+ words); failing personas are re-asked once with the violations appended to the user message (plus the other personas' headlines when the problem is a duplicate, unchanged or product-name headline). A rewrite also appends the current ad and the optional note, and its headline must differ from the current one |
| `copywriting_playbook.md` | Stage 2, rendered into `creative.md`'s `playbook` slot (`app/create.py` `_playbook`) | (part of `creative.md`) | `banned_phrases` (from tuning), `headline_max`, `body_max`, `cta_max` | The method every ad follows: persona motivation first, one fact as proof, a CTA for this persona on this publisher, a distinct angle (emotional / practical / proof), own words (no copied sentences), banned phrasing, limits |
| `creative_feedback.yaml` | Stage 2 retries, rewrites and violation chips (`app/create.py`, `app/copycheck.py`, loaded once by `app.prompts.feedback`) | none (text only) | per-key slots, e.g. `problems`, `headlines`, `name`, `number`, `word`, `phrase`, `field`/`n`/`limit`, `headline`/`body`/`cta`, `note` | Retry preamble, other-headlines sentence, rewrite (current ad, note) blocks, persona and publisher blocks, and every violation message code can raise |
| `category_words.yaml` | Stage 2 publisher block and the clarify `categories` slot (`app.prompts.category_word`) | none (text only) | none | How each publisher category is named to the models (`home` → "home goods") |
| `eval_candidates.md` (+ `eval_candidates_user.md`, `eval_buckets.yaml`) | Offline only: drafting eval candidates (`evals/generate.py`); the app never runs it | `OPENAI_MODEL_FAST` (gpt-5.4-mini) | `publishers` (catalog list), `given` (the 15 given examples, paraphrase bucket only), `n`, `bucket_desc` (from `eval_buckets.yaml`), `hint` | Candidate inputs with a suggested outcome and rationale, appended to `evals/candidates.jsonl` for hand review |
| `agents/strategist.md` | Step ① Strategist agent (`app/stepagents/strategist.py`), live runs (always with a steer; without one per `agents.run_without_steer`) | `OPENAI_MODEL_FAST` | none | Calls `read_brief`, `decide`, `rank_publishers(exclude_ids)`, `pick_personas(exclude_ids)`, `adjust_brief(add/remove categories, ages)`, `ask_questions`; returns `notes` (steer parts it could not apply; notes with digits are dropped). Code builds the result from the recorded choices |
| `agents/copywriter.md` | Step ② Copywriter agent, one per persona (`app/stepagents/creative.py`), also Regenerate | `OPENAI_MODEL_CREATIVE` | `product`, `facts`, `persona`, `publisher`, `others`, `playbook`, `headline_max`, `body_max`, `cta_max`, `rounds` | One ad (headline, body, cta, why) after up to `rounds` calls to `review_draft` (the Critic as a tool; later calls are refused by code) |
| `agents/critic.md` | Step ② Critic agent, called by the Copywriter | `OPENAI_MODEL_FAST` | `persona`, `publisher`, `playbook` | Calls `check_copy` (code's ad checks); `accept` + `notes`. It cannot accept what code rejects, and the final ad is re-checked by code anyway |
| `agents/media_planner.md` | Step ③ Media planner agent, only with a steer (`app/stepagents/planner.py`) | `OPENAI_MODEL_FAST` | `publishers` (the line items) | Calls `recommend_budget`, `set_budget` (accepted only if code finds that amount in the steer and it is within budget bounds), `exclude_publishers`, `set_pacing`, `preview_config`; code builds the config |
| `laya_questions.yaml` | Stage 1 Gate, only with `GATE_IMPL=laya` (`app/gate/laya_gate.py`) | Laya encoder (`convaiinnovations/laya`, `typed-decisions`), not an LLM | Laya state: `advertiser_text`, `brief_categories` | Four typed questions: `has_content`, `buyer`, `product_identifiable`, `category`, each with criteria |

Step agents (OpenAI Agents SDK, `app/stepagents/`): the user's steer goes in the agent's user
message inside `<user_steer>` tags (`wrap_steer`, at most `agents.steer_max_chars`), next to the
wrapped advertiser text; like a note, it is data. Agents never produce numbers: their tools wrap
the deterministic code, and each step's result is assembled by code from the tool outputs. Tool
docstrings in code are the tool schema descriptions (kept short); every instruction is here.

Reasoning effort for both OpenAI models is `OPENAI_REASONING_EFFORT` (default `low`). Limits used
in the slots (`headline_max` and so on) come from `config/tuning.yaml`.

## Code checks on every ad (`app/copycheck.py`)

The playbook asks; code enforces. Every ad is checked for:

- **Invented facts:** a number or claim word (`creative.claim_words`: "clinically", "proven", "#1"…)
  that the advertiser's text doesn't contain. Notes and Understand's `facts` never count as a
  source, only the raw text.
- **Length:** headline 60, body 160, CTA 30 characters.
- **Generic copy** (headline and body), unless the advertiser wrote it: age ranges ("ages 25-34",
  bare "18-24" when both ends are plausible ages), targeting echoes ("for women", from
  `creative.audience_words`), price bands ("under $50") and `creative.banned_phrases` (with
  inflections and hyphen variants).
- **Parroting:** 6 consecutive advertiser words (`creative.parrot_ngram`), or a whole advertiser
  sentence of 4+ words.
- **Headlines:** a duplicate of another persona's (token-set Jaccard ≥ 0.8), just the product name,
  or (on Regenerate) unchanged.

A failing persona is re-asked once with the problems appended; anything still failing ships with
`fact_violations`, shown as chips on the card and listed in one line when the ads are approved.
Regenerate rewrites one ad on the same publisher with the same checks; its note steers tone or
angle but is data, never a fact source.

Not prompts, but worth knowing:

- The default gate (`GATE_IMPL=llm`, `app/gate/llm_gate.py`) makes no call of its own. It reads
  `self_confidence`, `describes_business` and `audience_type` from the Understand brief.
- The `no_signal` outcome returns fixed questions (`NO_SIGNAL_QUESTIONS` in `app/create.py`), with no
  LLM call.

Editing any file here except this README and `agents/` changes the sample-cache fingerprint
(`app.samples.fingerprint`, with `config/tuning.yaml` minus its `agents:` block, and `data/*.json`): the samples
then run live until `make samples` re-runs them.
