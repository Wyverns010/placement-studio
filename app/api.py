"""The web layer: one route per step, plus health and the example buttons. The only file that knows
about FastAPI; the steps themselves are plain functions.

Pattern: layered architecture. This module is the thin HTTP shell; pipeline/brief/match/ads/plan are
the domain, llm/loaders/prompts the infrastructure. Routes validate, charge, then call one function."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import plan
from app.ads import write_ads
from app.constants.api import (
    MSG_BUDGET,
    MSG_BUSY,
    MSG_EMPTY,
    MSG_LLM,
    MSG_NO_ADS,
    MSG_OTHER,
    MSG_RATE_LIMIT,
)
from app.constants.brief import ANSWERS_HEADER
from app.constants.paths import WEB_DIST
from app.llm import CachedProvider, LLMError, LLMProvider, OpenAIProvider
from app.loaders import load_catalog, load_samples
from app.models.ads import Creative
from app.models.api import CampaignIn, ConfigIn, CreativesIn
from app.models.catalog import Catalog
from app.models.result import CampaignResult
from app.models.tuning import Tuning
from app.pipeline import stage1
from app.ratelimit import RateLimiter

log = logging.getLogger(__name__)
# Pattern: table-driven error mapping. One dict decides every error's status and safe message.
ERRORS = {LLMError: (502, MSG_LLM), Exception: (502, MSG_OTHER)}


@dataclass(frozen=True)
class Deps:
    """What every request uses, built once when the app starts.

    Pattern: dependency injection. Routes receive this through FastAPI's Depends(get_deps) rather
    than importing globals, so tests swap in a fake LLM by passing their own Deps to create_app.
    Frozen: the bundle is never reassigned (the limiter inside it keeps its own state)."""
    tuning: Tuning
    catalog: Catalog
    llm: LLMProvider
    limiter: RateLimiter


def get_deps(request: Request) -> Deps:
    return request.app.state.deps


def charge(request: Request, deps: Deps, cost: int) -> None:
    """429 when this client (the right-most X-Forwarded-For hop, added by our proxy) or everyone
    together is over the limit."""
    hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]
    client = hops[-1] if hops else (request.client.host if request.client else "unknown")
    refused = deps.limiter.check(client, cost)
    if refused:
        raise HTTPException(429, MSG_BUSY if refused == "global" else MSG_RATE_LIMIT)


def check_budget(budget_usd: float | None, tuning: Tuning) -> None:
    if budget_usd is not None and not tuning.budget.min_usd <= budget_usd <= tuning.budget.max_usd:
        raise HTTPException(422, MSG_BUDGET.format(low=tuning.budget.min_usd, high=tuning.budget.max_usd))


router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/samples")
def samples() -> list[dict]:
    return load_samples()


@router.post("/campaign")
def campaign(body: CampaignIn, request: Request, deps: Deps = Depends(get_deps)) -> CampaignResult:
    """Step 1. Clarify answers are appended to the text; a note comes with the brief to reuse."""
    text = body.text.strip()
    if not text:
        raise HTTPException(422, MSG_EMPTY)
    check_budget(body.budget_usd, deps.tuning)
    if body.answers:
        text += ANSWERS_HEADER + "\n".join(f"- {question}: {answer}" for question, answer in body.answers.items())
    charge(request, deps, deps.tuning.ratelimit.cost_campaign)
    return stage1(text, body.budget_usd, body.note, body.brief, llm=deps.llm, catalog=deps.catalog, tuning=deps.tuning)


@router.post("/creatives")
def ads(body: CreativesIn, request: Request, deps: Deps = Depends(get_deps)) -> list[Creative]:
    """Step 3: one ad per persona for step 1's result; the note is guidance for the writers."""
    result = body.result
    charge(request, deps, deps.tuning.ratelimit.cost_ads)
    creatives = write_ads(result.input_text, result.brief, result.publishers, result.personas, body.note, deps.llm,
                          deps.catalog, deps.tuning)
    if not creatives:
        raise HTTPException(502, MSG_NO_ADS)
    return creatives


@router.post("/config")
def config(body: ConfigIn, request: Request, deps: Deps = Depends(get_deps)) -> dict:
    """Step 4, code only and free; a note is read by one LLM call first (charged). No budget means
    the recommended one."""
    result, creatives, budget_usd, note = body.result, body.creatives, body.budget_usd, body.note
    check_budget(budget_usd, deps.tuning)
    budget, dropped, pacing, notes = budget_usd, set(), None, []
    if note:
        charge(request, deps, deps.tuning.ratelimit.cost_config_note)
        from_note, dropped, pacing, notes = plan.apply_note(note, result.publishers, deps.llm, deps.tuning)
        budget = budget if from_note is None else from_note
    built = plan.build_config(result.brief, result.publishers, result.personas, creatives, budget, deps.catalog,
                              deps.tuning, dropped, pacing)
    return {"config": built, "notes": notes}


def _handle_error(request: Request, error: Exception) -> JSONResponse:
    """The one place errors become responses: a safe message, never the error's own text."""
    status, message = next(answer for kind, answer in ERRORS.items() if isinstance(error, kind))
    log.error("request failed: %s", request.url.path, exc_info=error)
    return JSONResponse({"detail": message}, status_code=status)


def create_app(deps: Deps | None = None) -> FastAPI:
    """The app; tests pass their own deps, otherwise the real ones are loaded.

    Pattern: application factory and composition root. The only place real objects are built and
    wired together (OpenAI provider, optional disk cache around it, catalog, rate limiter)."""
    if deps is None:
        tuning = Tuning()
        llm = OpenAIProvider(tuning.llm_timeout_s)
        cache = os.getenv("LLM_CACHE_DIR")  # evals and local runs reuse earlier answers
        limits = tuning.ratelimit
        deps = Deps(tuning=tuning, catalog=load_catalog(), llm=CachedProvider(llm, Path(cache)) if cache else llm,
                    limiter=RateLimiter(limits.per_client_runs, limits.per_client_window_s,
                                        global_limit=limits.global_runs_per_hour))
    app = FastAPI(title="Placement Studio")
    app.state.deps = deps
    app.include_router(router)
    for kind in ERRORS:
        app.add_exception_handler(kind, _handle_error)
    # The built React app (web/dist) served at "/" so one process serves UI and API on one origin.
    # Mounted last: the /api routes above match first. Skipped in dev, where Vite serves the UI.
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


app = create_app()
