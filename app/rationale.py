"""Step 4: the one-line explanation under each config field, written from the config's own numbers."""
from __future__ import annotations

from app.constants.plan import PACE_WORDS
from app.models.brief import Brief
from app.models.plan import CampaignConfig
from app.models.scores import PublisherScore
from app.models.tuning import Tuning


def texts(config: CampaignConfig, brief: Brief, value: float, publishers: list[PublisherScore],
          tuning: Tuning) -> dict[str, str]:
    budget, bid, settings = config.budget, tuning.bid, tuning.budget
    cpa = config.bid_strategy["target_usd"]
    names = {score.publisher_id: score.name for score in publishers}
    goal = settings.learning_conversions_per_week * settings.weeks_per_month
    low, high = config.targeting["age_range"]
    cap = config.frequency_cap
    budget_text = (f"Recommended ${budget.recommended_usd:,.0f}/mo: {goal} conversions per publisher a month (what a CPA "
                   f"bid needs to leave learning) × ${cpa:,.0f} × {len(publishers)}, rounded up to "
                   f"${settings.round_to_usd:,.0f}. Split by fit")
    if budget.source == "user":
        budget_text += f". You set ${budget.monthly_usd:,.0f}/mo, which is used instead"
    first = config.line_items[0] if config.line_items else None
    projection = "No line items, so nothing to project" if first is None else (
        f"Impressions: budget ÷ CPM × 1,000 per publisher ({names.get(first.publisher_id, first.publisher_id)}: "
        f"${first.budget_usd:,.0f} ÷ ${first.cpm_usd:g} × 1,000 = {first.est_impressions:,}), "
        f"{budget.est_impressions:,} in all. Conversions: ${budget.monthly_usd:,.0f} ÷ ${cpa:,.0f} = "
        f"{budget.est_conversions:,}. Revenue: × ${value:,.0f} = ${budget.est_revenue_usd:,.0f}. "
        f"ROAS {budget.est_roas:g}×")
    return {
        "objective": "Conversions: the goal is " + ("subscription starts" if config.conversion_event ==
                                                    "subscription_start" else "purchases"),
        "bid_strategy": f"{bid.cpa_fraction_of_order_value:.0%} of ${value:,.0f} order value "
                        f"({'your price' if brief.price_usd else 'fit-weighted publisher AOV'}) = ${cpa:,.0f} target CPA",
        "budget": budget_text,
        "projection": projection,
        "targeting": f"{len(config.targeting['personas'])} personas, interests "
                     f"{', '.join(config.targeting['interests']) or 'none'}, "
                     f"{'all ages' if low is None else f'ages {low}-{high}'}, gender {config.targeting['gender']}, US",
        "frequency_cap": f"At most {cap['impressions']} per person every {cap['per_days']} days, by the "
                         f"{brief.price_tier} price tier (fewer, further apart for considered purchases)",
        "pacing": f"{PACE_WORDS[budget.pacing]}" + ("" if budget.pacing == "even" else ": from your note"),
        "guardrails": f"Pause if CPA exceeds ${config.guardrails['cpa_limit_usd']:,.0f} "
                      f"({bid.guardrail_cpa_multiple:g}× target) after {bid.guardrail_min_impressions:,} impressions",
        "line_items": f"{len(config.line_items)} publisher{'' if len(config.line_items) == 1 else 's'}, "
                      "budget by fit; each runs the ads written for it, or the best persona's ad",
    }
