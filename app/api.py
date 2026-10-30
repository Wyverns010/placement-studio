"""FastAPI app: JSON and SSE endpoints over the pipeline."""
from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from app import samples
from app.catalog import Catalog, load_catalog
from app.gate import ConfidenceGate, get_gate
from app.llm import LLMProvider, get_provider
from app.models import CampaignResult, StageEvent
from app.pipeline import PipelineError, collect, result_events, run_pipeline
from app.ratelimit import RateLimiter
from app.tuning import Tuning, load_tuning

RATE_LIMIT_MSG = "Demo limit reached — try a sample or wait a few minutes."
REPLAY_DELAY_S = 0.3

app = FastAPI(title="Placement Studio")
_limiter = RateLimiter(limit=12, window_s=600)


def get_limiter() -> RateLimiter:
    return _limiter


@lru_cache(maxsize=1)
def get_tuning() -> Tuning:
    return load_tuning()


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return load_catalog()


def get_llm() -> LLMProvider:
    return get_provider()


def get_gate_dep(t: Tuning = Depends(get_tuning)) -> ConfidenceGate:
    return get_gate(tuning=t)


class CampaignRequest(BaseModel):
    text: str
    budget_usd: float | None = None
    answers: dict[str, str] | None = None


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prepare(text: str, budget: float | None, answers: dict[str, str] | None,
             t: Tuning) -> tuple[str, float, bool]:
    """Validate and build the pipeline input. Returns (text, budget, has_answers)."""
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "Please describe your business.")
    text = text[: t.input.max_chars]
    b = t.budget
    if budget is None:
        budget = b.default_monthly_usd
    if not (b.min_usd <= budget <= b.max_usd):
        raise HTTPException(
            422, f"Budget must be between ${b.min_usd:,.0f} and ${b.max_usd:,.0f}.")
    if answers:
        answers = {str(q)[:200]: str(a)[:200] for q, a in list(answers.items())[:5]}
        text += "\n\nAdditional details:\n" + "\n".join(f"- {q}: {a}" for q, a in answers.items())
    return text, budget, bool(answers)


def _cached(text: str, budget: float, has_answers: bool, t: Tuning) -> CampaignResult | None:
    if has_answers:
        return None
    return samples.cached_result(text, budget, default_budget=t.budget.default_monthly_usd)


def _check_rate(request: Request, limiter: RateLimiter) -> None:
    if not limiter.allow(_client_key(request)):
        raise HTTPException(429, RATE_LIMIT_MSG)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/samples")
def list_samples():
    return samples.load_samples()


@app.post("/api/campaign")
async def campaign(req: CampaignRequest, request: Request,
                   llm: LLMProvider = Depends(get_llm), gate: ConfidenceGate = Depends(get_gate_dep),
                   catalog: Catalog = Depends(get_catalog), t: Tuning = Depends(get_tuning),
                   limiter: RateLimiter = Depends(get_limiter)):
    text, budget, has_answers = _prepare(req.text, req.budget_usd, req.answers, t)
    hit = _cached(text, budget, has_answers, t)
    if hit:
        return hit
    _check_rate(request, limiter)
    try:
        return await run_in_threadpool(
            lambda: collect(run_pipeline(text, budget, llm=llm, gate=gate, catalog=catalog, t=t)))
    except PipelineError as e:
        return JSONResponse({"detail": str(e)}, status_code=502)


@app.get("/api/campaign/stream")
async def campaign_stream(request: Request, text: str = "", budget_usd: float | None = None,
                          answers: str | None = Query(None),
                          llm: LLMProvider = Depends(get_llm),
                          gate: ConfidenceGate = Depends(get_gate_dep),
                          catalog: Catalog = Depends(get_catalog), t: Tuning = Depends(get_tuning),
                          limiter: RateLimiter = Depends(get_limiter)):
    parsed: dict[str, str] | None = None
    if answers:
        try:
            parsed = json.loads(answers)
            if not isinstance(parsed, dict):
                raise ValueError
            parsed = {str(k): str(v) for k, v in parsed.items()}
        except ValueError:
            raise HTTPException(422, "answers must be a JSON object.")
    full_text, budget, has_answers = _prepare(text, budget_usd, parsed, t)
    hit = _cached(full_text, budget, has_answers, t)
    if not hit:
        _check_rate(request, limiter)

    def encode(e: StageEvent) -> dict:
        return {"event": e.stage, "data": json.dumps(e.data)}

    async def gen():
        if hit:
            events = result_events(hit)
            for i, e in enumerate(events):
                if i:
                    await asyncio.sleep(REPLAY_DELAY_S)
                yield encode(e)
            return
        it = run_pipeline(full_text, budget, llm=llm, gate=gate, catalog=catalog, t=t)
        async for e in iterate_in_threadpool(it):
            yield encode(e)

    return EventSourceResponse(gen())


DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if DIST.is_dir():
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
