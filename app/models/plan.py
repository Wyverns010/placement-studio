from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel


class LineItem(BaseModel):
    publisher_id: str
    share: float
    budget_usd: float
    creative_id: str | None  # the primary ad on this publisher
    extra_creative_ids: list[str] = []  # other approved ads written for it, served in rotation
    cpm_usd: float = 0.0  # what 1,000 impressions cost here (by audience income)
    est_impressions: int = 0  # budget_usd / cpm_usd x 1,000


class BudgetBlock(TypedDict):
    """config.budget: typed and validated, but still a plain dict (same JSON, `cfg.budget["..."]`)."""
    monthly_usd: float
    recommended_usd: float
    source: Literal["recommended", "user"]
    pacing: Literal["front_loaded", "even", "accelerated"]
    unallocated_usd: float
    test_budget: bool
    conversions_goal: int  # per line item per month: learning conversions per week x weeks
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
    budget: BudgetBlock
    bid_strategy: dict  # {"type": "target_cpa", "target_usd": float}
    targeting: dict  # {"age_range", "gender", "geo", "interests", "personas"}
    line_items: list[LineItem]
    frequency_cap: dict  # {"impressions": int, "per_days": int}
    guardrails: dict  # {"pause_if_cpa_over_x": float, "cpa_limit_usd": float, "min_impressions": int}
    rationales: dict[str, str]  # field name -> one line, shown on hover
    decision_trace: dict
