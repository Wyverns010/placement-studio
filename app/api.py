"""The web layer: one route per step, plus health and the example buttons. The only file that knows
about FastAPI; the steps themselves are plain functions."""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import plan
from app.ads import write_ads
from app.constants.api import (
    MSG_BAD_AGES,
    MSG_BAD_PRICE,
    MSG_BUDGET,
    MSG_BUSY,
    MSG_EMPTY,
    MSG_LLM,
    MSG_NO_ADS,
    MSG_NO_PUBLISHERS,
    MSG_NOT_PROCEEDING,
    MSG_OTHER,
    MSG_RATE_LIMIT,
    MSG_UNKNOWN_ID,
    MSG_UNKNOWN_WORD,
)
from app.constants.brief import ANSWERS_HEADER
from app.constants.paths import WEB_DIST
from app.llm import CachedProvider, LLMError, LLMProvider, OpenAIProvider
from app.loaders import load_catalog, load_samples, load_tuning
from app.models.ads import Creative
from app.models.api import CampaignIn, Note
from app.models.brief import Brief
from app.models.catalog import Catalog
from app.models.result import CampaignResult
from app.models.tuning import Tuning
from app.pipeline import stage1
from app.ratelimit import RateLimiter

log = logging.getLogger(__name__)
ERRORS = {LLMError: (502, MSG_LLM), Exception: (502, MSG_OTHER)}


@dataclass(frozen=True)
class Services:
    """What every request uses, built once when the app starts."""
    tuning: Tuning
    catalog: Catalog
    llm: LLMProvider
    limiter: RateLimiter


def services(request: Request) -> Services:
    return request.app.state.services


def charge(request: Request, svc: Services, cost: int) -> None:
    """429 when this client (the right-most X-Forwarded-For hop, added by our proxy) or everyone
    together is over the limit."""
    hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]
    client = hops[-1] if hops else (request.client.host if request.client else "unknown")
    refused = svc.limiter.check(client, cost)
    if refused:
        raise HTTPException(429, MSG_BUSY if refused == "global" else MSG_RATE_LIMIT)


def check_budget(budget_usd: float | None, tuning: Tuning) -> None:
    if budget_usd is not None and not tuning.budget.min_usd <= budget_usd <= tuning.budget.max_usd:
        raise HTTPException(422, MSG_BUDGET.format(low=tuning.budget.min_usd, high=tuning.budget.max_usd))


def check_stage(svc: Services, brief: Brief | None, result: CampaignResult | None = None,
                creatives: list[Creative] = ()) -> None:
    """422 for anything the step code can't work with: a campaign the gate didn't let through, ids
    outside the catalog, category words outside the vocabulary, an impossible price or age."""
    catalog = svc.catalog
    if result is not None:
        if result.gate is None or result.gate.outcome != "proceed":
            raise HTTPException(422, MSG_NOT_PROCEEDING)
        ids = ([(p.publisher_id, catalog.publisher_by_id) for p in result.publishers]
               + [(p.persona_id, catalog.persona_by_id) for p in result.personas]
               + [(ad.publisher_id, catalog.publisher_by_id) for ad in creatives]
               + [(ad.persona_id, catalog.persona_by_id) for ad in creatives])
        if any(key not in known for key, known in ids):
            raise HTTPException(422, MSG_UNKNOWN_ID)
        if not any(p.recommended for p in result.publishers):
            raise HTTPException(422, MSG_NO_PUBLISHERS)
    if brief is None:
        return
    for field, words in (("categories", catalog.vocab), ("adjacent_categories", catalog.vocab),
                         ("conflicts", catalog.conflict_vocab)):
        if not set(getattr(brief, field)) <= set(words):
            raise HTTPException(422, MSG_UNKNOWN_WORD.format(field=field))
    if brief.price_usd is not None and not (math.isfinite(brief.price_usd) and brief.price_usd >= 0):
        raise HTTPException(422, MSG_BAD_PRICE)
    high = svc.tuning.input.brief_age_max
    if any(age is not None and not 0 <= age <= high for age in (brief.age_min, brief.age_max)):
        raise HTTPException(422, MSG_BAD_AGES.format(high=high))


router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/samples")
def samples() -> list[dict]:
    return load_samples()


@router.post("/campaign")
def campaign(body: CampaignIn, request: Request, svc: Services = Depends(services)) -> CampaignResult:
    """Step 1. Clarify answers are appended to the text; a note comes with the brief to reuse."""
    text = body.text.strip()
    if not text:
        raise HTTPException(422, MSG_EMPTY)
    check_budget(body.budget_usd, svc.tuning)
    check_stage(svc, body.brief)
    if body.answers:
        text += ANSWERS_HEADER + "\n".join(f"- {question}: {answer}" for question, answer in body.answers.items())
    charge(request, svc, svc.tuning.ratelimit.cost_campaign)
    return stage1(text, body.budget_usd, body.note, body.brief, llm=svc.llm, catalog=svc.catalog, tuning=svc.tuning)


@router.post("/creatives")
def ads(request: Request, result: CampaignResult, note: Note = Body(None),
        svc: Services = Depends(services)) -> dict:
    """Step 3: one ad per persona for step 1's result; the note is guidance for the writers."""
    check_stage(svc, result.brief, result)
    charge(request, svc, svc.tuning.ratelimit.cost_ads)
    creatives = write_ads(result.input_text, result.brief, result.publishers, result.personas, note, svc.llm,
                          svc.catalog, svc.tuning)
    if not creatives:
        raise HTTPException(502, MSG_NO_ADS)
    return {"creatives": creatives}


@router.post("/config")
def config(request: Request, result: CampaignResult, creatives: list[Creative], budget_usd: float | None = Body(None),
           note: Note = Body(None), svc: Services = Depends(services)) -> dict:
    """Step 4, code only and free; a note is read by one LLM call first (charged). No budget means
    the recommended one."""
    check_stage(svc, result.brief, result, creatives)
    check_budget(budget_usd, svc.tuning)
    budget, dropped, pacing, notes = budget_usd, set(), None, []
    if note:
        charge(request, svc, svc.tuning.ratelimit.cost_config_note)
        from_note, dropped, pacing, notes = plan.apply_note(note, result.publishers, svc.llm, svc.tuning)
        budget = budget if from_note is None else from_note
    built = plan.build_config(result.brief, result.publishers, result.personas, creatives, budget, svc.catalog,
                              svc.tuning, dropped, pacing)
    return {"config": built, "notes": notes}


def _handle_error(request: Request, error: Exception) -> JSONResponse:
    """The one place errors become responses: a safe message, never the error's own text."""
    status, message = next(answer for kind, answer in ERRORS.items() if isinstance(error, kind))
    log.error("request failed: %s", request.url.path, exc_info=error)
    return JSONResponse({"detail": message}, status_code=status)


def create_app(svc: Services | None = None) -> FastAPI:
    """The app; tests pass their own services, otherwise the real ones are loaded."""
    if svc is None:
        tuning = load_tuning()
        llm = OpenAIProvider(tuning.llm_timeout_s)
        cache = os.getenv("LLM_CACHE_DIR")  # evals and local runs reuse earlier answers
        limits = tuning.ratelimit
        svc = Services(tuning=tuning, catalog=load_catalog(), llm=CachedProvider(llm, Path(cache)) if cache else llm,
                       limiter=RateLimiter(limits.per_client_runs, limits.per_client_window_s,
                                           global_limit=limits.global_runs_per_hour))
    app = FastAPI(title="Placement Studio")
    app.state.services = svc
    app.include_router(router)
    for kind in ERRORS:
        app.add_exception_handler(kind, _handle_error)
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


app = create_app()
