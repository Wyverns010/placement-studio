from __future__ import annotations

from typing import Literal, NamedTuple

from pydantic import BaseModel

Pacing = Literal["front_loaded", "even", "accelerated"]


class LineItem(BaseModel):
    publisher_id: str
    share: float
    budget_usd: float
    cpm_usd: float  # what 1,000 impressions cost here (by audience income)
    est_impressions: int  # budget_usd / cpm_usd x 1,000
    ads: list[str]  # persona ids of the ads served here, the first is primary; the rest rotate


class Budget(BaseModel):
    monthly_usd: float
    recommended_usd: float
    source: Literal["recommended", "user"]
    pacing: Pacing
    unallocated_usd: float  # beyond what the publishers can absorb
    test_budget: bool  # a weak fit's small test
    est_impressions: int
    est_conversions: int  # spend / target CPA
    est_revenue_usd: float  # conversions x order value
    est_roas: float
    conversions_per_1k: float  # what the target CPA needs per 1,000 impressions
    cpa_is_stretch: bool  # above the plausible rate for checkout offers


class CampaignConfig(BaseModel):
    campaign_id: str
    objective: Literal["conversions"]
    conversion_event: Literal["purchase", "subscription_start"]
    budget: Budget
    bid_strategy: dict  # {"type": "target_cpa", "target_usd": float}
    targeting: dict  # {"age_range", "gender", "geo", "interests", "personas"}
    line_items: list[LineItem]
    frequency_cap: dict  # {"impressions": int, "per_days": int}
    guardrails: dict  # {"pause_if_cpa_over_x": float, "cpa_limit_usd": float, "min_impressions": int}
    rationales: dict[str, str]  # field name -> one line, shown on hover


class Recommendation(NamedTuple):
    usd: float  # what we recommend (the weak-fit test share when fit is weak)
    full_usd: float  # rounded and clamped, before any weak-fit test share
    cpa: float
    capped: list[str]  # publisher ids whose reach is below what the conversion goal needs


class PlanChanges(BaseModel):
    """What one LLM call reads from a step 4 note; code checks every field before applying it."""
    budget_usd: float | None
    drop_publishers: list[str]
    pacing: Pacing | None
    not_applied: list[str]  # parts of the note these fields can't express, one sentence each
