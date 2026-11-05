from __future__ import annotations

from typing import Literal

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
    self_confidence: float  # 0-1, the LLM's own read of how clear the product is


class GateResult(BaseModel):
    outcome: Outcome  # never "weak_fit" (decided after match)
    confidence: float  # the brief's clarity, shown against the threshold
    threshold: float


class ClarifyQuestion(BaseModel):
    question: str
    options: list[str]


class ClarifyBatch(BaseModel):
    questions: list[ClarifyQuestion]


class BriefChanges(BaseModel):
    """What one LLM call reads from a step 1 note; code checks every field before applying it."""
    drop_publishers: list[str]
    drop_personas: list[str]
    add_categories: list[str]
    remove_categories: list[str]
    age_min: int | None
    age_max: int | None
    not_applied: list[str]  # parts of the note these fields can't express, one sentence each
