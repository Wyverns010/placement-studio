# Prompts

Every prompt the app sends lives here and is read from disk at runtime (`app/prompts.py`
`render(name, **slots)`, which is `str.format_map`: a missing slot raises `KeyError`, and literal
braces are doubled). The advertiser's text never goes into a system prompt. It is sent as the user
message inside `<advertiser_text>` tags (`wrap_advertiser_text`), and each prompt treats it as data.

| File | Stage (caller) | Model | Slots | Output |
|---|---|---|---|---|
| `understand.md` | 1 Understand (`app/understand.py`) | `OPENAI_MODEL_FAST` (gpt-5.4-mini) | `vocab` (catalog categories), `conflict_vocab` | Structured brief; categories and conflicts are enums built from the catalog, so the model cannot invent a category |
| `clarify.md` | Clarify outcome only (`app/create.py` `clarify_questions`) | `OPENAI_MODEL_FAST` (gpt-5.4-mini) | `product`, `facts`, `unknowns`, `categories` | 1 to 3 questions, 2 to 5 tap-able options each |
| `creative.md` | 4 Create (`app/create.py` `_call_one`), one call per persona, in parallel | `OPENAI_MODEL_CREATIVE` (gpt-5.5) | `product`, `facts`, `headline_max`, `body_max`, `cta_max`, `personas` (this persona + its publisher), `others` (the other personas' angles) | One ad (headline, body, CTA, why). A code check (`check_facts`) rejects numbers, claim words or lengths not allowed; failing personas are re-asked once with the violations appended to the user message |
| `eval_candidates.md` (+ `eval_candidates_user.md`, `eval_buckets.yaml`) | Offline only: drafting eval candidates (`evals/generate.py`); the app never runs it | `OPENAI_MODEL_FAST` (gpt-5.4-mini) | `publishers` (catalog list), `given` (the 15 given examples, paraphrase bucket only), `n`, `bucket_desc` (from `eval_buckets.yaml`), `hint` | Candidate inputs with a suggested outcome and rationale, appended to `evals/candidates.jsonl` for hand review |
| `laya_questions.yaml` | 2 Gate, only with `GATE_IMPL=laya` (`app/gate/laya_gate.py`) | Laya encoder (`convaiinnovations/laya`, `typed-decisions`), not an LLM | Laya state: `advertiser_text`, `brief_categories` | Four typed questions: `has_content`, `buyer`, `product_identifiable`, `category`, each with criteria |

Reasoning effort for both OpenAI models is `OPENAI_REASONING_EFFORT` (default `low`). Limits used
in the slots (`headline_max` and so on) come from `config/tuning.yaml`.

Not prompts, but worth knowing:

- The default gate (`GATE_IMPL=llm`, `app/gate/llm_gate.py`) makes no call of its own. It reads
  `self_confidence`, `describes_business` and `audience_type` from the Understand brief.
- The `no_signal` outcome returns fixed questions (`NO_SIGNAL_QUESTIONS` in `app/create.py`), with no
  LLM call.
