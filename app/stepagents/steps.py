"""The three steps with their agents, each falling back to the plain code step on any agent
failure. Every result carries `mode` ("agent" | "fallback" | "code"), `agent_trace` and
`agent_notes`; the API adds "cached" for precomputed samples.

  stage1_events     Strategist          -> stage events (+ `agent` trace events while it works)
  creatives_step    Copywriter + Critic -> one ad per persona
  regenerate_step   Copywriter + Critic -> one rewritten ad
  config_step       Media planner       -> the campaign config (code builds it)
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Iterator

from app.catalog import Catalog
from app.gate import ConfidenceGate
from app.llm import LLMProvider
from app.models import (Brief, CampaignConfig, Creative, GateResult, PersonaScore, PublisherScore,
                        StageEvent)
from app.pipeline import Stage1Plan, make_config, make_creatives, regenerate, run_stage1
from app.stepagents import creative, planner, strategist
from app.stepagents.runtime import (AgentRuntime, CostCapExceeded, Session, run_step,
                                   wants_agent)
from app.tuning import Tuning

log = logging.getLogger(__name__)
CODE = {"mode": "code", "agent_trace": [], "agent_notes": []}
_DONE = object()


def stage1_events(text: str, budget_usd: float | None, steer: str | None, *, llm: LLMProvider,
                  gate: ConfidenceGate, catalog: Catalog, t: Tuning,
                  runtime: AgentRuntime | None) -> Iterator[StageEvent]:
    """Stage 1 events. With the agent: `agent` events (one per tool call) as it works, then the
    usual understood, gate, … done built by code from its choices."""
    if runtime is None or not wants_agent("strategist", steer, t):
        yield from run_stage1(text, budget_usd, llm=llm, gate=gate, catalog=catalog, t=t, meta=CODE)
        return
    steps: queue.Queue = queue.Queue()
    session = Session("strategist", runtime, t, on_step=steps.put)
    ws = strategist.Stage1Workspace(text, steer, llm=llm, gate=gate, catalog=catalog, t=t,
                                    session=session)
    box: dict = {}

    def work():
        try:
            run_step(lambda: strategist.run(ws, runtime), t, runtime)
        except BaseException as e:  # noqa: BLE001 - any agent failure falls back to code
            box["error"] = e
        finally:
            steps.put(_DONE)

    threading.Thread(target=work, daemon=True, name="strategist").start()
    while (item := steps.get()) is not _DONE:
        yield StageEvent(stage="agent", data=item.model_dump())
    if "error" in box:
        log.warning("strategist agent failed, falling back: %r", box["error"])
        meta = session.fallback_meta(box["error"])
        yield StageEvent(stage="agent", data=meta["agent_trace"][-1].model_dump())
        plan = Stage1Plan(brief=ws.understood) if ws.understood else None  # don't pay twice
        yield from run_stage1(text, budget_usd, llm=llm, gate=gate, catalog=catalog, t=t,
                              plan=plan, meta=meta)
        return
    yield from run_stage1(text, budget_usd, llm=llm, gate=gate, catalog=catalog, t=t,
                          plan=ws.plan(), meta=session.meta("agent"))


def _projected_over_cap(n_ads: int, session: Session) -> CostCapExceeded | None:
    """Decide before spending: if the team's expected cost is over the step's cap, the code
    writer runs straight away instead of paying for an agent run that would stop at the cap."""
    est = creative.projected_usd(n_ads, session.t)
    if est > session.cap:
        return CostCapExceeded(f"projected cost ${est:.2f} is over the ${session.cap:.2f} cap")
    return None


def creatives_step(text: str, brief: Brief, publishers: list[PublisherScore],
                   personas: list[PersonaScore], steer: str | None, *, llm: LLMProvider,
                   catalog: Catalog, t: Tuning,
                   runtime: AgentRuntime | None) -> tuple[list[Creative], dict]:
    """Stage 2: (creatives, meta). Code errors in the fallback propagate (the API maps them)."""
    def code():
        return make_creatives(text, brief, publishers, personas, llm=llm, catalog=catalog, t=t)

    if runtime is None or not wants_agent("creative", steer, t):
        return code(), dict(CODE)
    session = Session("creative", runtime, t)
    if (over := _projected_over_cap(creative.n_ads(personas, publishers, catalog), session)):
        return code(), session.fallback_meta(over)
    try:
        out = run_step(lambda: creative.write_all(text, brief, publishers, personas, steer,
                                                  catalog=catalog, t=t, runtime=runtime,
                                                  session=session), t, runtime)
        return out, session.meta("agent")
    except Exception as e:  # noqa: BLE001
        log.warning("creative agents failed, falling back: %r", e)
        meta = session.fallback_meta(e)
        return code(), meta


def regenerate_step(text: str, brief: Brief, publishers: list[PublisherScore],
                    personas: list[PersonaScore], creatives: list[Creative], persona_id: str,
                    note: str | None, steer: str | None, *, llm: LLMProvider, catalog: Catalog,
                    t: Tuning, runtime: AgentRuntime | None) -> tuple[Creative, dict]:
    def code():
        return regenerate(text, brief, publishers, personas, creatives, persona_id, note,
                          llm=llm, catalog=catalog, t=t)

    if runtime is None or not wants_agent("creative", steer or note, t):
        return code(), dict(CODE)
    session = Session("creative", runtime, t)
    if (over := _projected_over_cap(1, session)):
        return code(), session.fallback_meta(over)
    try:
        out = run_step(lambda: creative.rewrite_one(text, brief, publishers, personas, creatives,
                                                    persona_id, note, steer, catalog=catalog, t=t,
                                                    runtime=runtime, session=session), t, runtime)
        return out, session.meta("agent")
    except Exception as e:  # noqa: BLE001
        log.warning("creative agents failed on regenerate, falling back: %r", e)
        meta = session.fallback_meta(e)
        return code(), meta


def config_step(brief: Brief, gate: GateResult, publishers: list[PublisherScore],
                personas: list[PersonaScore], creatives: list[Creative], budget_usd: float | None,
                steer: str | None, *, catalog: Catalog, t: Tuning,
                runtime: AgentRuntime | None) -> tuple[CampaignConfig, dict]:
    """Stage 3: (config, meta). The config is always built by code; the planner only picks the
    budget (validated against the steer), exclusions and pacing."""
    def code():
        return make_config(brief, gate, publishers, personas, creatives, budget_usd,
                           catalog=catalog, t=t)

    if runtime is None or not wants_agent("media_planner", steer, t):
        return code(), dict(CODE)
    session = Session("media_planner", runtime, t)
    desk = planner.PlanDesk(brief, gate, publishers, personas, creatives, budget_usd, steer,
                            catalog=catalog, t=t, session=session)
    try:
        run_step(lambda: planner.run(desk, runtime), t, runtime)
        return desk.build(), session.meta("agent")
    except Exception as e:  # noqa: BLE001
        log.warning("media planner failed, falling back: %r", e)
        meta = session.fallback_meta(e)
        return code(), meta
