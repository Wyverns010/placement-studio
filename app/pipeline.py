"""The whole flow as one generator of stage events: understand -> gate -> match -> create -> config."""
from __future__ import annotations

import logging
from typing import Iterator

from app.catalog import Catalog
from app.config_builder import build_config
from app.create import NO_SIGNAL_QUESTIONS, clarify_questions, write_creatives
from app.gate import ConfidenceGate
from app.llm import LLMError, LLMProvider
from app.match import (
    is_weak_fit, mark_stretch, score_personas, score_publishers, select_personas,
)
from app.models import CampaignResult, PersonaScore, PublisherScore, StageEvent
from app.tuning import Tuning
from app.understand import understand

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


def _pub_data(pubs: list[PublisherScore], outcome: str = "proceed") -> dict:
    if outcome == "clarify":
        pubs = pubs[:3]  # faded best guess: top 3 only
    return {
        "recommended": [p.publisher_id for p in pubs if p.recommended],
        "top": [{"id": p.publisher_id, "name": p.name, "fit": p.fit} for p in pubs[:5]],
    }


def _persona_data(ps: list[PersonaScore]) -> dict:
    return {"selected": [{"id": p.persona_id, "name": p.name, "fit": p.fit, "stretch": p.stretch}
                         for p in ps]}


def result_events(r: CampaignResult) -> list[StageEvent]:
    """Stage events for an already-computed result (used to replay cached samples)."""
    ev: list[StageEvent] = []
    if r.brief:
        ev.append(StageEvent(stage="understood", data=r.brief.model_dump()))
    if r.gate:
        ev.append(StageEvent(stage="gate", data=r.gate.model_dump()))
    if r.publishers:
        ev.append(StageEvent(stage="publishers", data=_pub_data(r.publishers, r.outcome)))
    if r.personas:
        ev.append(StageEvent(stage="personas", data=_persona_data(r.personas)))
    if r.creatives:
        ev.append(StageEvent(stage="creatives", data={"count": len(r.creatives)}))
    if r.config:
        ev.append(StageEvent(stage="config", data={"line_items": len(r.config.line_items)}))
    ev.append(StageEvent(stage="done", data=r.model_dump()))
    return ev


def run_pipeline(text: str, budget_usd: float, *, llm: LLMProvider, gate: ConfidenceGate,
                 catalog: Catalog, t: Tuning) -> Iterator[StageEvent]:
    try:
        yield from _run(text, budget_usd, llm, gate, catalog, t)
    except LLMError:
        log.exception("pipeline LLM failure")
        yield StageEvent(stage="error", data={"message": MSG_LLM})
    except Exception:
        log.exception("pipeline failure")
        yield StageEvent(stage="error", data={"message": MSG_OTHER})


def _run(text, budget_usd, llm, gate, catalog, t) -> Iterator[StageEvent]:
    def result(outcome, message=None, publishers=(), personas=(), creatives=(), clarify=(),
               config=None) -> CampaignResult:
        return CampaignResult(
            input_text=text, budget_usd=budget_usd, outcome=outcome, message=message,
            brief=brief, gate=g, publishers=list(publishers), personas=list(personas),
            creatives=list(creatives), clarify=list(clarify), config=config,
        )

    brief = understand(text, catalog, llm)
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
        yield StageEvent(stage="publishers", data=_pub_data(excluded))
        yield StageEvent(stage="done", data=result(
            "out_of_scope", msg_out_of_scope(brief.product, brief.audience_type), publishers=excluded).model_dump())
        return

    persona_scores = score_personas(brief, catalog, t)

    if g.outcome == "clarify":
        yield StageEvent(stage="publishers", data=_pub_data(scored, "clarify"))
        top = select_personas(persona_scores, t)[:1]
        yield StageEvent(stage="personas", data=_persona_data(top))
        questions = clarify_questions(text, brief, llm, catalog)
        yield StageEvent(stage="done", data=result(
            "clarify", None, publishers=scored, personas=top, clarify=questions).model_dump())
        return

    weak = is_weak_fit(scored, t)
    if weak:
        scored = mark_stretch(scored, t)
    recommended = [s for s in scored if s.recommended]
    yield StageEvent(stage="publishers", data=_pub_data(scored))
    personas = select_personas(persona_scores, t)
    yield StageEvent(stage="personas", data=_persona_data(personas))
    creatives = write_creatives(text, brief, personas, recommended, catalog, llm, t)
    yield StageEvent(stage="creatives", data={"count": len(creatives)})
    config = build_config(brief=brief, gate=g, publishers=recommended, personas=personas,
                          creatives=creatives, monthly_usd=budget_usd, weak_fit=weak,
                          catalog=catalog, t=t)
    yield StageEvent(stage="config", data={"line_items": len(config.line_items)})
    outcome = "weak_fit" if weak else "proceed"
    message = msg_weak_fit(brief.product, len(recommended)) if weak else None
    yield StageEvent(stage="done", data=result(
        outcome, message, publishers=scored, personas=personas, creatives=creatives,
        config=config).model_dump())


def collect(events: Iterator[StageEvent]) -> CampaignResult:
    for e in events:
        if e.stage == "done":
            return CampaignResult.model_validate(e.data)
        if e.stage == "error":
            raise PipelineError(e.data.get("message", MSG_OTHER))
    raise PipelineError(MSG_OTHER)
