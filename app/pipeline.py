"""The flow in three stages the client drives, plus `run_full` that chains them for evals.

1. run_stage1: understand -> gate -> match, as a generator of stage events (SSE).
2. make_creatives / regenerate: one ad per selected persona (LLM), or a rewrite of one.
3. make_config: the campaign config (code only).
"""
from __future__ import annotations

import logging
from typing import Iterator

from app.catalog import Catalog
from app.config_builder import build_config
from app.create import NO_SIGNAL_QUESTIONS, clarify_questions, rewrite_creative, write_creatives
from app.gate import ConfidenceGate
from app.llm import LLMError, LLMProvider
from app.match import (
    is_weak_fit, mark_stretch, score_personas, score_publishers, select_personas,
)
from app.models import (Brief, CampaignConfig, CampaignResult, Creative, GateResult,
                        PersonaScore, PublisherScore, StageEvent)
from app.tuning import Tuning
from app.understand import clamp_brief, understand

log = logging.getLogger(__name__)

MSG_LLM = "The AI service didn't respond — try again or pick a sample."
MSG_OTHER = "Something went wrong building this campaign."
MSG_NO_SIGNAL = "Nothing to go on yet — tell us a little about what you sell."


def msg_weak_fit(product: str | None, n: int) -> str:
    return (f"Nothing in this catalog is a strong match for {product or 'this product'}. "
            f"These are the closest {n} — run them as a small test.")


def msg_out_of_scope(product: str | None, audience_type: str = "business") -> str:
    if audience_type == "not_shoppable":
        return (f"This catalog reaches online shoppers at checkout; {product or 'this'} isn't "
                "something they buy there, so we don't recommend spending here.")
    return (f"This catalog reaches shoppers at checkout; {product or 'this product'} sells to "
            "business buyers, so we don't recommend spending here.")


class PipelineError(Exception):
    """Raised by collect() when the stream ended in an error event; message is user-safe."""


def _pub_data(pubs: list[PublisherScore], t: Tuning, outcome: str = "proceed") -> dict:
    if outcome == "clarify":
        pubs = pubs[: t.stage1.clarify_publishers_shown]  # faded best guess: top N only
    return {
        "recommended": [p.publisher_id for p in pubs if p.recommended],
        "top": [{"id": p.publisher_id, "name": p.name, "fit": p.fit}
                for p in pubs[: t.stage1.top_publishers_shown]],
    }


def _persona_data(ps: list[PersonaScore]) -> dict:
    return {"selected": [{"id": p.persona_id, "name": p.name, "fit": p.fit, "stretch": p.stretch}
                         for p in ps]}


def result_events(r: CampaignResult, t: Tuning) -> list[StageEvent]:
    """Stage events for an already-computed result (used to replay cached samples)."""
    ev: list[StageEvent] = []
    if r.brief:
        ev.append(StageEvent(stage="understood", data=r.brief.model_dump()))
    if r.gate:
        ev.append(StageEvent(stage="gate", data=r.gate.model_dump()))
    if r.publishers:
        ev.append(StageEvent(stage="publishers", data=_pub_data(r.publishers, t, r.outcome)))
    if r.personas:
        ev.append(StageEvent(stage="personas", data=_persona_data(r.personas)))
    ev.append(StageEvent(stage="done", data=r.model_dump()))
    return ev


def run_stage1(text: str, budget_usd: float | None, *, llm: LLMProvider, gate: ConfidenceGate,
               catalog: Catalog, t: Tuning) -> Iterator[StageEvent]:
    """Stage 1 events: understood, gate, [publishers, personas,] done | error. `budget_usd` is only
    echoed in the result (the client passes it on to stage 3)."""
    try:
        yield from _run(text, budget_usd, llm, gate, catalog, t)
    except LLMError:
        log.exception("pipeline LLM failure")
        yield StageEvent(stage="error", data={"message": MSG_LLM})
    except Exception:
        log.exception("pipeline failure")
        yield StageEvent(stage="error", data={"message": MSG_OTHER})


def _run(text, budget_usd, llm, gate, catalog, t) -> Iterator[StageEvent]:
    def result(outcome, message=None, publishers=(), personas=(), clarify=()) -> CampaignResult:
        return CampaignResult(
            input_text=text, budget_usd=budget_usd, outcome=outcome, message=message,
            brief=brief, gate=g, publishers=list(publishers), personas=list(personas),
            creatives=[], clarify=list(clarify), config=None,
        )

    brief = clamp_brief(understand(text, catalog, llm), t)  # within the caps stage 2/3 enforce
    yield StageEvent(stage="understood", data=brief.model_dump())
    g = gate.assess(text, brief)
    yield StageEvent(stage="gate", data=g.model_dump())

    if g.outcome == "no_signal":
        yield StageEvent(stage="done", data=result("no_signal", MSG_NO_SIGNAL,
                                                   clarify=NO_SIGNAL_QUESTIONS).model_dump())
        return

    scored = score_publishers(brief, catalog, t)

    if g.outcome == "out_of_scope":
        excluded = [s.model_copy(update={"recommended": False, "stretch": False}) for s in scored]
        yield StageEvent(stage="publishers", data=_pub_data(excluded, t))
        yield StageEvent(stage="done", data=result(
            "out_of_scope", msg_out_of_scope(brief.product, brief.audience_type), publishers=excluded).model_dump())
        return

    persona_scores = score_personas(brief, catalog, t)

    if g.outcome == "clarify":
        yield StageEvent(stage="publishers", data=_pub_data(scored, t, "clarify"))
        top = select_personas(persona_scores, t)[:1]
        yield StageEvent(stage="personas", data=_persona_data(top))
        questions = clarify_questions(text, brief, llm, catalog, t)
        yield StageEvent(stage="done", data=result(
            "clarify", None, publishers=scored, personas=top, clarify=questions).model_dump())
        return

    weak = is_weak_fit(scored, t)
    if weak:
        scored = mark_stretch(scored, t)
    yield StageEvent(stage="publishers", data=_pub_data(scored, t))
    personas = select_personas(persona_scores, t)
    yield StageEvent(stage="personas", data=_persona_data(personas))
    outcome = "weak_fit" if weak else "proceed"
    message = msg_weak_fit(brief.product, sum(s.recommended for s in scored)) if weak else None
    yield StageEvent(stage="done", data=result(
        outcome, message, publishers=scored, personas=personas).model_dump())


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
                *, catalog: Catalog, t: Tuning) -> CampaignConfig:
    """Stage 3 (code only): `budget_usd` None means use the recommended budget."""
    return build_config(brief=brief, gate=gate, publishers=recommended_of(publishers),
                        personas=personas, creatives=creatives, monthly_usd=budget_usd,
                        weak_fit=is_weak(publishers), catalog=catalog, t=t)


BUILT = ("proceed", "weak_fit")


def run_full(text: str, budget_usd: float | None = None, *, llm: LLMProvider,
             gate: ConfidenceGate, catalog: Catalog, t: Tuning) -> CampaignResult:
    """All three stages in one call (evals, precompute). Raises PipelineError for a stage-1
    error and lets stage-2 errors (e.g. LLMError) propagate."""
    r = collect(run_stage1(text, budget_usd, llm=llm, gate=gate, catalog=catalog, t=t))
    if r.outcome not in BUILT:
        return r
    creatives = make_creatives(text, r.brief, r.publishers, r.personas, llm=llm, catalog=catalog, t=t)
    config = make_config(r.brief, r.gate, r.publishers, r.personas, creatives, budget_usd,
                         catalog=catalog, t=t)
    return r.model_copy(update={"creatives": creatives, "config": config})


def collect(events: Iterator[StageEvent]) -> CampaignResult:
    for e in events:
        if e.stage == "done":
            return CampaignResult.model_validate(e.data)
        if e.stage == "error":
            raise PipelineError(e.data.get("message", MSG_OTHER))
    raise PipelineError(MSG_OTHER)
