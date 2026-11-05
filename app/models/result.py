from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.models.ads import Creative
from app.models.brief import Brief, ClarifyQuestion, GateResult, Outcome
from app.models.plan import CampaignConfig
from app.models.scores import PersonaScore, PublisherScore

Mode = Literal["agent", "fallback", "code"]


class TraceStep(BaseModel):
    """One step an agent took (a tool call, or the fallback), shown in "What the agent did"."""
    agent: str
    tool: str
    args_summary: str
    result_summary: str
    ms: int


class CampaignResult(BaseModel):
    """Stage 1 fills everything but creatives and config; run_full fills those too."""
    input_text: str
    budget_usd: float | None = None  # the user's budget, if any, echoed for stage 3
    outcome: Outcome
    message: str | None
    brief: Brief | None
    gate: GateResult | None
    publishers: list[PublisherScore]
    personas: list[PersonaScore]
    creatives: list[Creative]
    clarify: list[ClarifyQuestion]
    config: CampaignConfig | None
    # step agents (outside the signed fields): how this result was made and what the agent did
    mode: Mode | None = None  # agent | fallback (agent failed, code ran) | code (no agent)
    agent_trace: list[TraceStep] = []
    agent_notes: list[str] = []


class StageEvent(BaseModel):
    stage: Literal["agent", "understood", "gate", "publishers", "personas", "done", "error"]
    data: dict
