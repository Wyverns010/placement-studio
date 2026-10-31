from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel

Outcome = Literal["proceed", "clarify", "out_of_scope", "no_signal", "weak_fit"]
PriceTier = Literal["value", "mid", "premium", "luxury", "unknown"]


class Brief(BaseModel):
    describes_business: bool  # false for "idk just try it"
    product: str | None
    # not_shoppable: nothing a shopper buys online (local in-person service, job ad, charity, politics)
    audience_type: Literal["consumer", "business", "not_shoppable", "unclear"]
    categories: list[str]  # subset of catalog.vocab: direct fit
    adjacent_categories: list[str]  # subset of catalog.vocab: related
    conflicts: list[str]  # subset of catalog.conflict_vocab the product embodies
    price_usd: float | None
    price_tier: PriceTier
    business_model: Literal["subscription", "one_off", "unknown"]
    age_min: int | None
    age_max: int | None
    gender_skew: Literal["female", "male", "balanced", "unknown"]
    facts: list[str]  # claims stated in the input, verbatim-ish
    unknowns: list[str]  # what's missing that would change the plan
    self_confidence: float  # 0-1, LLM's own read of clarity (LLM gate only)


class GateResult(BaseModel):
    outcome: Outcome  # never "weak_fit" (decided after match)
    confidence: float
    threshold: float
    impl: Literal["llm"]
    signals: dict[str, float | str]  # raw per-question values, shown in Details


class Factor(BaseModel):
    name: str
    score: float
    note: str


class PublisherScore(BaseModel):
    publisher_id: str
    name: str
    fit: float
    factors: list[Factor]
    recommended: bool
    stretch: bool
    reason: str  # about 8 words max


class PersonaScore(BaseModel):
    persona_id: str
    name: str
    fit: float
    factors: list[Factor]
    stretch: bool


class Creative(BaseModel):
    creative_id: str
    persona_id: str
    publisher_id: str
    headline: str
    body: str
    cta: str
    why: str
    fact_violations: list[str] = []


class ClarifyQuestion(BaseModel):
    question: str
    options: list[str]


class LineItem(BaseModel):
    publisher_id: str
    share: float
    budget_usd: float
    creative_id: str | None  # the primary ad on this publisher
    extra_creative_ids: list[str] = []  # other approved ads written for it, served in rotation


class BudgetBlock(TypedDict):
    """config.budget: typed and validated, but still a plain dict (same JSON, `cfg.budget["..."]`)."""
    monthly_usd: float
    recommended_usd: float
    source: Literal["recommended", "user"]
    pacing: Literal["front_loaded", "even", "accelerated"]
    unallocated_usd: float
    test_budget: bool


class CampaignConfig(BaseModel):
    campaign_id: str
    objective: Literal["conversions"]
    conversion_event: Literal["purchase", "subscription_start"]
    budget: BudgetBlock
    bid_strategy: dict  # {"type": "target_cpa", "target_usd": float}
    targeting: dict  # {"age_range", "gender", "geo", "interests", "personas"}
    line_items: list[LineItem]
    frequency_cap: dict  # {"impressions": int, "per_days": int}
    guardrails: dict  # {"pause_if_cpa_over_x": float, "cpa_limit_usd": float, "min_impressions": int}
    rationales: dict[str, str]  # field name -> one line, shown on hover
    decision_trace: dict


Mode = Literal["agent", "fallback", "cached", "code"]


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
    stage_token: str | None = None  # API only: HMAC over the stage-1 fields (app/stagesign.py)
    # step agents (outside the signed fields): how this result was made and what the agent did
    mode: Mode | None = None  # agent | fallback (agent failed, code ran) | cached | code (no agent)
    agent_trace: list[TraceStep] = []
    agent_notes: list[str] = []


class StageEvent(BaseModel):
    stage: Literal["agent", "understood", "gate", "publishers", "personas", "done", "error"]
    data: dict
