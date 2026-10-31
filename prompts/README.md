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
| `understand.md` | Stage 1 Understand (`app/understand.py`) | `OPENAI_MODEL_FAST` (gpt-5.4-mini) | `vocab` (catalog categories), `conflict_vocab` | Structured brief; categories and conflicts are enums built from the catalog, so the model cannot invent a category |
| `clarify.md` | Stage 1, clarify outcome only (`app/create.py` `clarify_questions`) | `OPENAI_MODEL_FAST` (gpt-5.4-mini) | `product`, `facts`, `unknowns`, `categories` | 1 to 3 questions, 2 to 5 tap-able options each |
| `creative.md` | Stage 2 Create (`app/create.py` `_call_one`): one call per persona, in parallel (`write_creatives`), or one call to rewrite an ad (`rewrite_creative`, Regenerate) | `OPENAI_MODEL_CREATIVE` (gpt-5.4-mini; gpt-5.5 opt-in) | `product`, `facts`, `headline_max`, `body_max`, `cta_max`, `personas` (this persona's block), `publisher` (publisher context: category, audience ages/gender/income, AOV, notes), `others` (the other personas' angles), `playbook` (rendered `copywriting_playbook.md`) | One ad (headline, body, CTA, why). Code (`ad_problems`) rejects numbers, claim words or lengths not allowed and generic copy (age ranges, "for women"-style targeting echoes, "under $N", `creative.banned_phrases`) the advertiser didn't write; failing personas are re-asked once with the violations appended to the user message (plus the other personas' headlines when the problem is a duplicate, unchanged or product-name headline). A rewrite also appends the current ad and the optional note, and its headline must differ from the current one |
| `copywriting_playbook.md` | Stage 2, rendered into `creative.md`'s `playbook` slot (`app/create.py` `_playbook`) | (part of `creative.md`) | `banned_phrases` (from tuning), `headline_max`, `body_max`, `cta_max` | The six-step method every ad follows: persona motivation, benefit-first hook with one true detail, publisher context, three silent angles, banned phrasing, limits |
| `creative_feedback.yaml` | Stage 2 retries, rewrites and violation chips (`app/create.py`, loaded by `app.prompts.feedback`) | none (text only) | per-key slots, e.g. `problems`, `headlines`, `name`, `number`, `word`, `phrase`, `field`/`n`/`limit`, `headline`/`body`/`cta`, `note` | Retry preamble, other-headlines sentence, rewrite (current ad, note) blocks, persona and publisher blocks, and every violation message code can raise |
| `eval_candidates.md` (+ `eval_candidates_user.md`, `eval_buckets.yaml`) | Offline only: drafting eval candidates (`evals/generate.py`); the app never runs it | `OPENAI_MODEL_FAST` (gpt-5.4-mini) | `publishers` (catalog list), `given` (the 15 given examples, paraphrase bucket only), `n`, `bucket_desc` (from `eval_buckets.yaml`), `hint` | Candidate inputs with a suggested outcome and rationale, appended to `evals/candidates.jsonl` for hand review |
| `laya_questions.yaml` | Stage 1 Gate, only with `GATE_IMPL=laya` (`app/gate/laya_gate.py`) | Laya encoder (`convaiinnovations/laya`, `typed-decisions`), not an LLM | Laya state: `advertiser_text`, `brief_categories` | Four typed questions: `has_content`, `buyer`, `product_identifiable`, `category`, each with criteria |

Reasoning effort for both OpenAI models is `OPENAI_REASONING_EFFORT` (default `low`). Limits used
in the slots (`headline_max` and so on) come from `config/tuning.yaml`.

Not prompts, but worth knowing:

- The default gate (`GATE_IMPL=llm`, `app/gate/llm_gate.py`) makes no call of its own. It reads
  `self_confidence`, `describes_business` and `audience_type` from the Understand brief.
- The `no_signal` outcome returns fixed questions (`NO_SIGNAL_QUESTIONS` in `app/create.py`), with no
  LLM call.
