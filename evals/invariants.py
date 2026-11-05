"""Rules every result must obey, whatever the outcome. Only what the types can't guarantee."""
from __future__ import annotations

from app.models.result import CampaignResult
from app.models.tuning import Tuning


def check(result: CampaignResult, tuning: Tuning) -> list[str]:
    failures: list[str] = []
    outcome, config = result.outcome, result.config
    for publisher in result.publishers:
        if len(publisher.factors) != 4:
            failures.append(f"publisher {publisher.publisher_id}: {len(publisher.factors)} factors, expected 4")
        if not publisher.reason.strip():
            failures.append(f"publisher {publisher.publisher_id}: empty reason")
    if outcome not in ("proceed", "weak_fit"):
        if config is not None or result.creatives:
            failures.append(f"{outcome}: must have no ads and no config")
        return failures
    if not 3 <= len(result.personas) <= 5:
        failures.append(f"{outcome}: {len(result.personas)} personas, expected 3-5")
    if len(result.creatives) != len(result.personas):
        failures.append(f"{outcome}: {len(result.creatives)} ads for {len(result.personas)} personas")
    if config is None:
        return failures + [f"{outcome}: config is None"]
    budget = config.budget
    if abs(sum(item.share for item in config.line_items) - 1.0) > 1e-6:
        failures.append("line item shares don't sum to 1")
    if not tuning.budget.min_usd <= budget.recommended_usd <= tuning.budget.max_usd:
        failures.append(f"recommended budget {budget.recommended_usd} outside the bounds")
    elif budget.source == "recommended" and budget.monthly_usd != budget.recommended_usd:
        failures.append("budget source is recommended but monthly != recommended")
    if outcome == "weak_fit" and budget.source == "recommended" and not budget.test_budget:
        failures.append("weak_fit: no test budget")
    placed = {persona_id for item in config.line_items for persona_id in item.ads}
    failures += [f"ad {ad.persona_id} is not in any line item" for ad in result.creatives if ad.persona_id not in placed]
    return failures
