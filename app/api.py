"""FastAPI app over the three stages. Stateless: each stage-2/3 request carries back what the
client received from the stage before, re-validated here with the Pydantic models.

  POST /api/campaign, GET /api/campaign/stream   stage 1 (understand, gate, match)   counts as a run
  POST /api/creatives                            stage 2 (one ad per persona)        counts as a run
  POST /api/creatives/regenerate                 stage 2 (rewrite one ad)            counts as a run
  POST /api/config                               stage 3 (config, code only)         free
Stage 1 results carry a stage_token (app/stagesign.py); stages 2 and 3 must send it back with
the exact stage-1 objects or get 403. Cached samples (stage 1 and their creatives) skip the LLM
and the rate limit. Each step runs its agent (app/stepagents) when there is an optional `steer`
(or per tuning `agents.run_without_steer`); responses add mode, agent_trace and agent_notes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from dotenv import load_dotenv

from app import samples, stagesign
from app.catalog import Catalog, load_catalog
from app.gate import ConfidenceGate, get_gate
from app.llm import LLMError, LLMProvider, get_provider
from app.models import (Brief, CampaignConfig, CampaignResult, Creative, GateResult, Mode,
                        PersonaScore, PublisherScore, StageEvent, TraceStep)
from app.pipeline import (MSG_LLM, MSG_OTHER, PipelineError, collect, recommended_of,
                          result_events)
from app.stepagents.runtime import AgentRuntime, openai_runtime
from app.stepagents.steps import config_step, creatives_step, regenerate_step, stage1_events
from app.ratelimit import RateLimiter
from app.tuning import Tuning, load_tuning

load_dotenv()  # never overrides env vars already set

RATE_LIMIT_MSG = "Demo limit reached — try a sample or wait a few minutes."
BUSY_MSG = "The demo is busy — try a sample or come back in a bit."
NO_ADS_MSG = "The AI service didn't return any ads — try again."
TAMPERED_MSG = "This campaign changed or expired — run it again."
NOT_PROCEEDING_MSG = "Ads and a config are only built for a campaign the gate let through."
TOO_LARGE_MSG = "Request too large."
BAD_CHARS_MSG = "The request contains invalid characters."


def _check_encodable(*values) -> None:
    """422 for text that cannot be UTF-8 encoded (lone surrogates), before it can 500 a response."""
    try:
        json.dumps(values, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        raise HTTPException(422, BAD_CHARS_MSG)

log = logging.getLogger(__name__)

app = FastAPI(title="Placement Studio")


class BodyLimit:
    """Refuse request bodies over input.max_body_bytes with 413 (Content-Length or streamed)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        limit = get_tuning().input.max_body_bytes
        length = dict(scope.get("headers") or []).get(b"content-length", b"")
        if length.isdigit() and int(length) > limit:
            return await JSONResponse({"detail": TOO_LARGE_MSG}, status_code=413)(scope, receive, send)
        seen = 0

        async def guarded():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    raise HTTPException(413, TOO_LARGE_MSG)  # FastAPI re-raises HTTPException
            return msg

        return await self.inner(scope, guarded, send)


app.add_middleware(BodyLimit)


@lru_cache(maxsize=1)
def get_tuning() -> Tuning:
    return load_tuning()


@lru_cache(maxsize=1)
def get_limiter() -> RateLimiter:
    """One process-wide limiter: live runs per client per window, plus a global hourly cap."""
    r = get_tuning().ratelimit
    return RateLimiter(limit=r.per_client_runs, window_s=r.per_client_window_s,
                       global_limit=r.global_runs_per_hour)


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return load_catalog()


def get_llm() -> LLMProvider:
    return get_provider()


def get_gate_dep(t: Tuning = Depends(get_tuning)) -> ConfidenceGate:
    return get_gate(tuning=t)


@lru_cache(maxsize=1)
def get_agent_runtime() -> AgentRuntime | None:
    """The step agents' runtime; None (plain code, mode "code") when disabled or keyless."""
    return openai_runtime(get_tuning())


class CampaignRequest(BaseModel):
    text: str
    budget_usd: float | None = None  # optional; only echoed back for stage 3
    answers: dict[str, str] | None = None
    steer: str | None = None  # "Tell the agent…" (data, at most agents.steer_max_chars)


class CreativesRequest(BaseModel):
    """Stage 2: what stage 1 returned, unchanged, with its stage_token."""
    input_text: str
    brief: Brief
    gate: GateResult
    publishers: list[PublisherScore]
    personas: list[PersonaScore]
    stage_token: str
    steer: str | None = None  # step-level note for the step's agent(s); data


class RegenerateRequest(CreativesRequest):
    creatives: list[Creative]
    persona_id: str
    note: str | None = None


class ConfigRequest(CreativesRequest):
    """Stage 3: budget_usd omitted means use the recommended budget."""
    creatives: list[Creative]
    budget_usd: float | None = None


class AgentMeta(BaseModel):
    """How a step result was made: agent, fallback (the agent failed; code ran), cached, code."""
    mode: Mode = "code"
    agent_trace: list[TraceStep] = []
    agent_notes: list[str] = []


class CreativesResponse(AgentMeta):
    creatives: list[Creative]


class CreativeResponse(AgentMeta):
    creative: Creative


class ConfigResponse(AgentMeta):
    config: CampaignConfig


def _client_key(request: Request) -> str:
    """The right-most X-Forwarded-For hop: the one our trusted proxy (HF) appended. Earlier
    entries are whatever the client sent, so keying on them would let anyone mint new buckets."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        hops = [h.strip() for h in fwd.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


def _check_budget(budget: float | None, t: Tuning) -> None:
    b = t.budget
    if budget is not None and not (b.min_usd <= budget <= b.max_usd):
        raise HTTPException(
            422, f"Budget must be between ${b.min_usd:,.0f} and ${b.max_usd:,.0f}.")


ANSWERS_HEADER = "\n\nAdditional details:\n"


def _prepare(text: str, budget: float | None, answers: dict[str, str] | None,
             t: Tuning) -> tuple[str, float | None, bool]:
    """Validate and build the stage-1 input. Returns (text, budget, has_answers)."""
    _check_encodable(text, answers)
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "Please describe your business.")
    text = text[: t.input.max_chars]
    _check_budget(budget, t)
    if answers:
        n, cap = t.input.max_answers, t.input.max_answer_chars
        answers = {str(q)[:cap]: str(a)[:cap] for q, a in list(answers.items())[:n]}
        text += ANSWERS_HEADER + "\n".join(f"- {q}: {a}" for q, a in answers.items())
    return text, budget, bool(answers)


def _cached(text: str, budget: float | None, has_answers: bool,
            steer: str | None = None) -> CampaignResult | None:
    """A precomputed sample, only for its exact text with no answers and no steer."""
    if has_answers or steer:
        return None
    hit = samples.cached_stage1(text, budget)
    return hit.model_copy(update={"mode": "cached", "agent_trace": [], "agent_notes": []}) if hit else None


STEER_TOO_LONG = "Keep the note to {n} characters."


def _steer(steer: str | None, t: Tuning) -> str | None:
    """The trimmed steer (None if blank); 422 if over agents.steer_max_chars."""
    _check_encodable(steer)
    steer = (steer or "").strip() or None
    if steer and len(steer) > t.agents.steer_max_chars:
        raise HTTPException(422, STEER_TOO_LONG.format(n=t.agents.steer_max_chars))
    return steer


def _max_input_chars(t: Tuning) -> int:
    """Longest input_text stage 1 can produce: the text plus the capped clarify answers."""
    line = len("- : \n") + 2 * t.input.max_answer_chars
    return t.input.max_chars + len(ANSWERS_HEADER) + t.input.max_answers * line


def _signed(r: CampaignResult) -> dict:
    return stagesign.sign_result(r).model_dump()


def _check_brief(b: Brief, catalog: Catalog, t: Tuning) -> None:
    """Size and vocabulary caps on an echoed brief (defence in depth behind the stage token)."""
    i = t.input
    if b.product and len(b.product) > i.brief_product_max_chars:
        raise HTTPException(422, "brief.product is too long.")
    for name in ("facts", "unknowns"):
        items = getattr(b, name)
        if len(items) > i.brief_list_max_items:
            raise HTTPException(422, f"brief.{name} has too many items.")
        if any(len(x) > i.brief_item_max_chars for x in items):
            raise HTTPException(422, f"brief.{name} has an item that is too long.")
    for name, vocab in (("categories", catalog.vocab), ("adjacent_categories", catalog.vocab),
                        ("conflicts", catalog.conflict_vocab)):
        items = getattr(b, name)
        if len(items) > i.brief_categories_max:
            raise HTTPException(422, f"brief.{name} has too many items.")
        if not set(items) <= set(vocab):
            raise HTTPException(422, f"brief.{name} has an unknown term.")
    if b.price_usd is not None and not (math.isfinite(b.price_usd) and b.price_usd >= 0):
        raise HTTPException(422, "brief.price_usd must be a finite amount of at least 0.")
    if any(a is not None and not 0 <= a <= i.brief_age_max for a in (b.age_min, b.age_max)):
        raise HTTPException(422, f"brief ages must be between 0 and {i.brief_age_max}.")


def _validate_stage(req: CreativesRequest, catalog: Catalog, t: Tuning) -> str:
    """Shared checks for stage 2/3 requests, in order: the stage token (403), the gate let it
    through, then sizes and ids (422). Returns the stripped input_text."""
    _check_encodable(req.model_dump(mode="json"))
    if not stagesign.verify(req.stage_token, req.input_text, req.brief, req.gate, req.publishers,
                            req.personas):
        raise HTTPException(403, TAMPERED_MSG)
    if req.gate.outcome != "proceed":
        raise HTTPException(422, NOT_PROCEEDING_MSG)
    text = (req.input_text or "").strip()
    if not text:
        raise HTTPException(422, "Please describe your business.")
    if len(text) > _max_input_chars(t):
        raise HTTPException(422, "input_text is longer than stage 1 produces.")
    _check_brief(req.brief, catalog, t)
    known_pubs = {p.id for p in catalog.publishers}
    known_personas = {p.id for p in catalog.personas}
    creatives = getattr(req, "creatives", [])
    if any(p.publisher_id not in known_pubs for p in req.publishers):
        raise HTTPException(422, "Unknown publisher in the request.")
    if len({p.publisher_id for p in req.publishers}) != len(req.publishers):
        raise HTTPException(422, "Duplicate publisher ids.")
    if not recommended_of(req.publishers):
        raise HTTPException(422, "No recommended publishers to place ads on.")
    if not 1 <= len(req.personas) <= t.persona.max:
        raise HTTPException(422, f"Send between 1 and {t.persona.max} personas.")
    if any(p.persona_id not in known_personas for p in req.personas):
        raise HTTPException(422, "Unknown persona in the request.")
    if len({p.persona_id for p in req.personas}) != len(req.personas):
        raise HTTPException(422, "Duplicate persona ids.")
    for c in creatives:
        if c.persona_id not in known_personas or c.publisher_id not in known_pubs:
            raise HTTPException(422, "Unknown persona or publisher in a creative.")
    if (len({c.creative_id for c in creatives}) != len(creatives)
            or len({c.persona_id for c in creatives}) != len(creatives)):
        raise HTTPException(422, "Duplicate creative ids.")
    if len(creatives) > t.persona.max:
        raise HTTPException(422, f"Send at most {t.persona.max} creatives.")
    return text


async def _live(fn):
    """Run a stage-2 call in a thread; map failures to a user-safe 502."""
    try:
        return await run_in_threadpool(fn)
    except LLMError:
        log.exception("stage 2 LLM failure")
        raise HTTPException(502, MSG_LLM)
    except HTTPException:
        raise
    except Exception:
        log.exception("stage 2 failure")
        raise HTTPException(502, MSG_OTHER)


def _check_rate(request: Request, limiter: RateLimiter, cost: int) -> None:
    refused = limiter.check(_client_key(request), cost)
    if refused:
        raise HTTPException(429, BUSY_MSG if refused == "global" else RATE_LIMIT_MSG)


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
                   limiter: RateLimiter = Depends(get_limiter),
                   runtime: AgentRuntime | None = Depends(get_agent_runtime)):
    text, budget, has_answers = _prepare(req.text, req.budget_usd, req.answers, t)
    steer = _steer(req.steer, t)
    hit = _cached(text, budget, has_answers, steer)
    if hit:
        return _signed(hit)
    _check_rate(request, limiter, t.ratelimit.cost_stage1)
    try:
        return _signed(await run_in_threadpool(
            lambda: collect(stage1_events(text, budget, steer, llm=llm, gate=gate, catalog=catalog,
                                          t=t, runtime=runtime))))
    except PipelineError as e:
        return JSONResponse({"detail": str(e)}, status_code=502)


@app.get("/api/campaign/stream")
async def campaign_stream(request: Request, text: str = "", budget_usd: float | None = None,
                          answers: str | None = Query(None), steer: str | None = Query(None),
                          llm: LLMProvider = Depends(get_llm),
                          gate: ConfidenceGate = Depends(get_gate_dep),
                          catalog: Catalog = Depends(get_catalog), t: Tuning = Depends(get_tuning),
                          limiter: RateLimiter = Depends(get_limiter),
                          runtime: AgentRuntime | None = Depends(get_agent_runtime)):
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
    steer = _steer(steer, t)
    hit = _cached(full_text, budget, has_answers, steer)
    if not hit:
        _check_rate(request, limiter, t.ratelimit.cost_stage1)

    def encode(e: StageEvent) -> dict:
        data = _signed(CampaignResult.model_validate(e.data)) if e.stage == "done" else e.data
        return {"event": e.stage, "data": json.dumps(data)}

    async def gen():
        if hit:
            events = result_events(hit, t)
            for i, e in enumerate(events):
                if i:
                    await asyncio.sleep(t.api.replay_delay_s)
                yield encode(e)
            return
        it = stage1_events(full_text, budget, steer, llm=llm, gate=gate, catalog=catalog, t=t,
                           runtime=runtime)
        async for e in iterate_in_threadpool(it):
            yield encode(e)

    return EventSourceResponse(gen())


@app.post("/api/creatives", response_model=CreativesResponse)
async def creatives(req: CreativesRequest, request: Request,
                    llm: LLMProvider = Depends(get_llm), catalog: Catalog = Depends(get_catalog),
                    t: Tuning = Depends(get_tuning), limiter: RateLimiter = Depends(get_limiter),
                    runtime: AgentRuntime | None = Depends(get_agent_runtime)):
    text = _validate_stage(req, catalog, t)
    steer = _steer(req.steer, t)
    hit = None if steer else samples.cached_creatives(text, req.publishers, req.personas)
    if hit:
        return {"creatives": hit, "mode": "cached"}
    _check_rate(request, limiter, t.ratelimit.cost_creatives)
    out, meta = await _live(lambda: creatives_step(text, req.brief, req.publishers, req.personas,
                                                   steer, llm=llm, catalog=catalog, t=t,
                                                   runtime=runtime))
    if not out:
        raise HTTPException(502, NO_ADS_MSG)
    return {"creatives": out, **meta}


@app.post("/api/creatives/regenerate", response_model=CreativeResponse)
async def regenerate_creative(req: RegenerateRequest, request: Request,
                              llm: LLMProvider = Depends(get_llm),
                              catalog: Catalog = Depends(get_catalog),
                              t: Tuning = Depends(get_tuning),
                              limiter: RateLimiter = Depends(get_limiter),
                              runtime: AgentRuntime | None = Depends(get_agent_runtime)):
    text = _validate_stage(req, catalog, t)
    steer = _steer(req.steer, t)
    if not any(c.persona_id == req.persona_id for c in req.creatives):
        raise HTTPException(422, "persona_id has no creative to regenerate.")
    note = (req.note or "").strip() or None
    if note and len(note) > t.creative.note_max_chars:
        raise HTTPException(422, f"Keep the note to {t.creative.note_max_chars} characters.")
    _check_rate(request, limiter, t.ratelimit.cost_regenerate)
    out, meta = await _live(lambda: regenerate_step(
        text, req.brief, req.publishers, req.personas, req.creatives, req.persona_id, note, steer,
        llm=llm, catalog=catalog, t=t, runtime=runtime))
    return {"creative": out, **meta}


@app.post("/api/config", response_model=ConfigResponse)
def config(req: ConfigRequest, request: Request, catalog: Catalog = Depends(get_catalog),
           t: Tuning = Depends(get_tuning), limiter: RateLimiter = Depends(get_limiter),
           runtime: AgentRuntime | None = Depends(get_agent_runtime)):
    """Code only and free; with a steer the media planner agent runs first (rate limited)."""
    _validate_stage(req, catalog, t)
    _check_budget(req.budget_usd, t)
    steer = _steer(req.steer, t)
    if steer and runtime is not None:
        _check_rate(request, limiter, t.agents.ratelimit_cost_config)
    cfg, meta = config_step(req.brief, req.gate, req.publishers, req.personas, req.creatives,
                            req.budget_usd, steer, catalog=catalog, t=t, runtime=runtime)
    return {"config": cfg, **meta}


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
