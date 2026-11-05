"""Step 1 from text to result, and `run_full`, which chains all the steps for the evals."""
from __future__ import annotations

from app.brief import apply_note, clarify_questions, decide, understand
from app.config_builder import build_config
from app.constants.brief import (
    BUSINESS_PROB,
    NO_SIGNAL_QUESTIONS,
    NOTE_GATE,
    NOTE_KEEP_ONE,
)
from app.constants.pipeline import (
    MSG_BUSINESS,
    MSG_NO_FIT,
    MSG_NO_SIGNAL,
    MSG_NOT_SHOPPABLE,
    MSG_WEAK_FIT,
)
from app.create import rewrite_creative, write_creatives
from app.llm import LLMProvider
from app.match import pick_publishers, score_personas, score_publishers, select_personas
from app.models.ads import Creative
from app.models.brief import Brief, GateResult
from app.models.catalog import Catalog
from app.models.plan import CampaignConfig
from app.models.result import CampaignResult
from app.models.scores import PersonaScore, PublisherScore
from app.models.tuning import Tuning


def stage1(text: str, budget_usd: float | None, note: str | None, brief: Brief | None, *,
           llm: LLMProvider, catalog: Catalog, tuning: Tuning) -> CampaignResult:
    """Read the text (or reuse the brief sent back with a note), decide, match publishers, then personas.
    The gate reads what the advertiser wrote; a note only changes matching."""
    base = brief or understand(text, catalog, llm, tuning)
    gate = decide(1.0 if base.describes_business else 0.0, BUSINESS_PROB[base.audience_type],
                  base.self_confidence, tuning.gate)
    current, dropped_publishers, dropped_personas, notes = base, set(), set(), []
    if note and gate.outcome == "proceed":
        current, dropped_publishers, dropped_personas, notes = apply_note(note, base, llm, catalog, tuning)
    elif note:
        notes = [NOTE_GATE.format(outcome=gate.outcome)]
    shared = dict(input_text=text, budget_usd=budget_usd, brief=current, gate=gate, creatives=[],
                  config=None, mode="agent" if note else "code", agent_notes=notes)
    if gate.outcome == "no_signal":
        return CampaignResult(**shared, outcome="no_signal", message=MSG_NO_SIGNAL, publishers=[],
                              personas=[], clarify=NO_SIGNAL_QUESTIONS)
    if gate.outcome == "out_of_scope":
        excluded = [score.model_copy(update={"recommended": False, "stretch": False})
                    for score in score_publishers(current, catalog, tuning)]
        template = MSG_NOT_SHOPPABLE if current.audience_type == "not_shoppable" else MSG_BUSINESS
        default = "this" if current.audience_type == "not_shoppable" else "this product"
        return CampaignResult(**shared, outcome="out_of_scope", publishers=excluded, personas=[], clarify=[],
                              message=template.format(product=current.product or default))
    if gate.outcome == "clarify":
        scores = score_publishers(current, catalog, tuning)
        recommended = [score for score in scores if score.recommended]
        preview = select_personas(score_personas(current, catalog, tuning, recommended), tuning)[:1]
        return CampaignResult(**shared, outcome="clarify", message=None, publishers=scores, personas=preview,
                              clarify=clarify_questions(text, current, llm, catalog, tuning))
    scores, weak = pick_publishers(current, catalog, tuning, dropped_publishers)
    if dropped_publishers and not any(score.recommended for score in scores):
        notes.append(NOTE_KEEP_ONE)
        scores, weak = pick_publishers(current, catalog, tuning)
    recommended = [score for score in scores if score.recommended]
    personas = select_personas([score for score in score_personas(current, catalog, tuning, recommended)
                                if score.persona_id not in dropped_personas], tuning)
    message = None
    if weak:
        product = current.product or "this product"
        message = (MSG_WEAK_FIT.format(product=product, n=len(recommended)) if recommended
                   else MSG_NO_FIT.format(product=product))
    return CampaignResult(**shared, outcome="weak_fit" if weak else "proceed", message=message,
                          publishers=scores, personas=personas, clarify=[])


def recommended_of(publishers: list[PublisherScore]) -> list[PublisherScore]:
    return [p for p in publishers if p.recommended]


def is_weak(publishers: list[PublisherScore]) -> bool:
    """Stage 1 marks a weak fit's closest publishers as recommended stretch picks."""
    return any(p.recommended and p.stretch for p in publishers)


def make_creatives(text: str, brief: Brief, publishers: list[PublisherScore],
                   personas: list[PersonaScore], *, llm: LLMProvider, catalog: Catalog,
                   t: Tuning) -> list[Creative]:
    """Stage 2: one ad per persona, on distinct recommended publishers where possible."""
    return write_creatives(text, brief, personas, recommended_of(publishers), catalog, llm, t)


def regenerate(text: str, brief: Brief, publishers: list[PublisherScore],
               personas: list[PersonaScore], creatives: list[Creative], persona_id: str,
               note: str | None, *, llm: LLMProvider, catalog: Catalog, t: Tuning) -> Creative:
    """Stage 2: rewrite one persona's ad (same publisher), optionally steered by a note."""
    return rewrite_creative(text, brief, personas, publishers, creatives, persona_id, note,
                            catalog, llm, t)


def make_config(brief: Brief, gate: GateResult, publishers: list[PublisherScore],
                personas: list[PersonaScore], creatives: list[Creative], budget_usd: float | None,
                *, catalog: Catalog, t: Tuning, exclude: frozenset[str] = frozenset(),
                pacing_override: str | None = None) -> CampaignConfig:
    """Stage 3 (code only): `budget_usd` None means use the recommended budget. `exclude` drops
    publishers from the line items and `pacing_override` sets pacing (the media planner's choices)."""
    return build_config(brief=brief, gate=gate,
                        publishers=[p for p in recommended_of(publishers) if p.publisher_id not in exclude],
                        personas=personas, creatives=creatives, monthly_usd=budget_usd,
                        weak_fit=is_weak(publishers), catalog=catalog, t=t,
                        pacing_override=pacing_override)


def run_full(text: str, budget_usd: float | None = None, *, llm: LLMProvider, catalog: Catalog,
             tuning: Tuning) -> CampaignResult:
    """All steps in one call, for the evals: step 1, then ads and config when a campaign is built."""
    result = stage1(text, budget_usd, None, None, llm=llm, catalog=catalog, tuning=tuning)
    if result.outcome not in ("proceed", "weak_fit"):
        return result
    creatives = make_creatives(text, result.brief, result.publishers, result.personas, llm=llm,
                               catalog=catalog, t=tuning)
    config = make_config(result.brief, result.gate, result.publishers, result.personas, creatives, budget_usd,
                         catalog=catalog, t=tuning)
    return result.model_copy(update={"creatives": creatives, "config": config})
