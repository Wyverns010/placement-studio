"""Step 4: the one-line explanation under each config field, written from the config's own numbers."""
from __future__ import annotations

import re

from app.constants.plan import PACE_WORDS
from app.models.ads import Creative
from app.models.brief import Brief
from app.models.catalog import Catalog
from app.models.plan import CampaignConfig, Recommendation
from app.models.scores import PersonaScore, PublisherScore
from app.models.tuning import Tuning


def texts(config: CampaignConfig, brief: Brief, recommendation: Recommendation, value_per_order: float,
          weak_fit: bool, code_pacing: str, publishers: list[PublisherScore], persona_scores: list[PersonaScore],
          ads: list[Creative], prices: dict[str, tuple[float, float]], catalog: Catalog,
          tuning: Tuning) -> dict[str, str]:
    bid, budget = tuning.bid, config.budget
    subscription = brief.business_model == "subscription"
    multiplier = bid.subscription_ltv_multiplier if subscription else 1
    cpa = config.bid_strategy["target_usd"]
    source = "your price" if brief.price_usd else "fit-weighted publisher AOV"
    ltv = f" × {bid.subscription_ltv_multiplier:.1f} subscription LTV" if subscription else ""
    low, high = config.targeting["age_range"]
    ages = ("all ages" if low is None and high is None else f"ages up to {high}" if low is None
            else f"ages {low}+" if high is None else f"ages {low}-{high}")
    interests = config.targeting["interests"]
    reason = _pacing_reason(brief, weak_fit, code_pacing, budget.monthly_usd, recommendation.usd)
    if budget.pacing == code_pacing:
        pacing = f"{PACE_WORDS[code_pacing]}: {reason}"
    else:
        pacing = f"{PACE_WORDS[budget.pacing]}: you asked for it (we'd pick {PACE_WORDS[code_pacing].lower()}: {reason})"
    return {
        "objective": "Conversions: the goal is " + ("subscription starts" if subscription else "purchases"),
        "bid_strategy": f"{bid.cpa_fraction_of_order_value:.0%} of ${value_per_order:,.0f} order value ({source})"
                        f"{ltv} = ${cpa:,.0f} target CPA",
        "budget": _budget_text(config, recommendation, weak_fit, publishers, prices, catalog, tuning),
        "projection": _projection_text(config, value_per_order * multiplier, publishers, subscription, tuning),
        "targeting": f"{len(persona_scores)} personas, interests {', '.join(interests) or 'none'}, {ages}, "
                     f"gender {config.targeting['gender']}, US",
        "frequency_cap": _frequency_text(brief, weak_fit, config.frequency_cap["impressions"],
                                         config.frequency_cap["per_days"], tuning),
        "pacing": pacing,
        "guardrails": f"Pause if CPA exceeds ${config.guardrails['cpa_limit_usd']:,.0f} "
                      f"({bid.guardrail_cpa_multiple:g}× target) after {bid.guardrail_min_impressions:,} impressions",
        "line_items": _line_items_text(config, publishers, persona_scores, ads, tuning),
    }


def _budget_text(config: CampaignConfig, recommendation: Recommendation, weak_fit: bool,
                 publishers: list[PublisherScore], prices: dict[str, tuple[float, float]], catalog: Catalog,
                 tuning: Tuning) -> str:
    """Goal x CPA per publisher, reach caps, rounding, the weak-fit test and the user's own number."""
    settings, budget = tuning.budget, config.budget
    count = len(publishers)
    goal = settings.learning_conversions_per_week * settings.weeks_per_month
    names = {score.publisher_id: score.name for score in publishers}
    text = (f"Recommended ${recommendation.usd:,.0f}/mo. Goal: {goal} conversions per publisher a month "
            f"({settings.learning_conversions_per_week} a week, what a CPA bid needs to leave learning) × "
            f"${recommendation.cpa:,.0f} target CPA = ${recommendation.cpa * goal:,.0f} each, across {count} "
            f"publisher{'' if count == 1 else 's'}")
    for publisher_id in recommendation.capped:
        publisher = catalog.publisher_by_id[publisher_id]
        cpm, cap = prices[publisher_id]
        text += (f"; {names.get(publisher_id, publisher_id)} capped at its reach ({settings.max_share_of_impressions:.0%} of "
                 f"{publisher.monthly_impressions / 1e6:g}M impressions at ${cpm:g} CPM = ${cap:,.0f})")
    text += f". Rounded up to ${settings.round_to_usd:,.0f}, within ${settings.min_usd:,.0f}–${settings.max_usd:,.0f}"
    if weak_fit:
        share = recommendation.full_usd * settings.weak_fit_test_fraction
        text += (f", then a test because fit is weak: {settings.weak_fit_test_fraction:.0%} of "
                 f"${recommendation.full_usd:,.0f}, capped at ${settings.weak_fit_test_max_usd:,.0f}, "
                 f"rounded to ${settings.round_to_usd:,.0f}")
        if min(share, settings.weak_fit_test_max_usd) < settings.min_usd:
            text += f" (raised to the ${settings.min_usd:,.0f} minimum)"
    if budget.source == "user" and weak_fit:
        text += (f". You chose ${budget.monthly_usd:,.0f}; we'd suggest a ${recommendation.usd:,.0f} test because "
                 "nothing in the catalog is a strong match")
    elif budget.source == "user":
        text += f". You set ${budget.monthly_usd:,.0f}/mo, which is used instead"
    text += (". Split by fit; each publisher's CPM follows its audience's income "
             f"({', '.join(f'{tier} ${cpm:g}' for tier, cpm in settings.cpm_by_income_usd.items())})")
    if budget.unallocated_usd:
        text += f"; ${budget.unallocated_usd:,.0f} unallocated (beyond publisher reach)"
    return text


def _projection_text(config: CampaignConfig, value: float, publishers: list[PublisherScore], subscription: bool,
                     tuning: Tuning) -> str:
    """The projection with its arithmetic, the first line item as the worked example."""
    if not config.line_items:
        return "No line items, so nothing to project"
    budget, item = config.budget, config.line_items[0]
    cpa, spend = config.bid_strategy["target_usd"], budget.monthly_usd
    names = {score.publisher_id: score.name for score in publishers}
    fraction = tuning.bid.cpa_fraction_of_order_value
    kind = "subscription value (order value × LTV)" if subscription else "order value"
    text = (f"Impressions: each publisher's budget ÷ its CPM × 1,000, added up "
            f"({names.get(item.publisher_id, item.publisher_id)}: ${item.budget_usd:,.0f} ÷ ${item.cpm_usd:g} × 1,000 "
            f"= {item.est_impressions:,}) = {budget.est_impressions:,}. "
            f"Conversions: ${spend:,.0f} ÷ ${cpa:,.0f} target CPA = {budget.est_conversions:,}. "
            f"Revenue: {budget.est_conversions:,} × ${value:,.0f} {kind} = ${budget.est_revenue_usd:,.0f}. "
            f"ROAS: ${budget.est_revenue_usd:,.0f} ÷ ${spend:,.0f} = {budget.est_roas:g}× (about 1 ÷ "
            f"{fraction:.0%}, because the CPA is {fraction:.0%} of that value). "
            f"Check: {budget.est_conversions:,} ÷ {budget.est_impressions:,} impressions = "
            f"{budget.conversions_per_1k:g} conversions per 1,000 impressions")
    ceiling = tuning.budget.max_conversions_per_1k_impressions
    if budget.cpa_is_stretch:
        return text + f", above the ~{ceiling:g} per 1,000 checkout offers usually reach: the CPA is optimistic"
    return text + f", under the ~{ceiling:g} per 1,000 checkout offers usually reach, so the CPA is realistic"


def _frequency_text(brief: Brief, weak_fit: bool, impressions: int, per_days: int, tuning: Tuning) -> str:
    settings = tuning.frequency
    tier = brief.price_tier if brief.price_tier in settings.by_price_tier else "unknown"
    base = settings.by_price_tier[tier]
    parts = [f"{tier} price tier: {base.impressions} per {base.per_days} days"]
    if brief.business_model == "subscription":
        parts.append(f"+{settings.subscription_extra} for a subscription")
    if weak_fit:
        parts.append(f"−{settings.weak_fit_reduction} for a weak-fit test")
        if per_days < base.per_days:
            parts.append(f"window shortened to {per_days} days so the test learns fast")
    return (f"At most {impressions} impression{'' if impressions == 1 else 's'} per person every {per_days} days "
            f"({', '.join(parts)})")


def _pacing_reason(brief: Brief, weak_fit: bool, pacing: str, monthly_usd: float, recommended_usd: float) -> str:
    """Why code picks this pacing (the text after "Even: ", "Accelerated: " and so on)."""
    if weak_fit:
        return "a small weak-fit test should learn fast"
    if pacing == "accelerated":
        return (f"a {brief.price_tier}-tier buy with ${monthly_usd:,.0f} below the ${recommended_usd:,.0f} "
                "recommendation, so spend it while it converts")
    if brief.price_tier in ("premium", "luxury"):
        return f"a {brief.price_tier}-tier purchase is considered, so reminders are spread out"
    if monthly_usd >= recommended_usd:
        return f"${monthly_usd:,.0f} meets the ${recommended_usd:,.0f} recommendation"
    return f"{brief.price_tier} price tier"


def _line_items_text(config: CampaignConfig, publishers: list[PublisherScore], persona_scores: list[PersonaScore],
                     ads: list[Creative], tuning: Tuning) -> str:
    """The split rule, ads rotating on one publisher, and ads reused from another publisher."""
    items = config.line_items
    names = {score.publisher_id: score.name for score in publishers}
    persona_names = {score.persona_id: score.name for score in persona_scores}
    by_persona = {ad.persona_id: ad for ad in ads}
    text = (f"{len(items)} publisher{'' if len(items) == 1 else 's'}, budget share proportional to fit with a "
            f"{tuning.budget.min_share:.0%} floor")
    rotating = [f"{len(item.ads)} ads rotate on {names.get(item.publisher_id, item.publisher_id)}"
                for item in items if len(item.ads) > 1]
    if rotating:
        text += "; " + ", ".join(rotating) + " (each written for that publisher)"
    reused = []
    for item in items:
        ad = by_persona.get(item.ads[0]) if item.ads else None
        if ad and ad.publisher_id != item.publisher_id:
            persona = re.sub(r"^the\s+", "", persona_names.get(ad.persona_id, ad.persona_id), flags=re.IGNORECASE)
            reused.append(f"{names.get(item.publisher_id, item.publisher_id)} reuses the {persona} ad written for "
                          f"{names.get(ad.publisher_id, ad.publisher_id)}")
    return text + ("; " + ", ".join(reused) if reused else "")
