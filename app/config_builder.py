from __future__ import annotations

import hashlib
import re

from app.budget import allocate, order_value_used, target_cpa
from app.catalog import Catalog
from app.models import (Brief, CampaignConfig, Creative, GateResult, LineItem,
                        PersonaScore, PublisherScore)
from app.tuning import Tuning

ID_SLUG_LEN = 32  # identifier formatting, not a tunable
ID_HASH_LEN = 6
GEO = ["US"]  # every catalog publisher is US-based


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _campaign_id(brief: Brief, publishers: list[PublisherScore], personas: list[PersonaScore],
                 monthly_usd: float) -> str:
    key = "|".join([brief.model_dump_json(), str(monthly_usd),
                    ",".join(p.publisher_id for p in publishers),
                    ",".join(p.persona_id for p in personas)])
    digest = hashlib.sha1(key.encode()).hexdigest()[:ID_HASH_LEN]
    return f"cmp_{_slug(brief.product or 'campaign')[:ID_SLUG_LEN]}_{digest}"


def _dedup(xs: list[str]) -> list[str]:
    return list(dict.fromkeys(xs))


def _assign_creatives(items: list[LineItem], personas: list[PersonaScore],
                      creatives: list[Creative]) -> list[LineItem]:
    if not creatives:
        return items
    rank = {p.persona_id: i for i, p in enumerate(personas)}
    ordered = sorted(creatives, key=lambda c: rank.get(c.persona_id, len(rank)))
    best_persona = max(personas, key=lambda p: p.fit).persona_id if personas else None
    fallback = next((c for c in ordered if c.persona_id == best_persona), ordered[0])
    out = []
    for li in items:
        own = next((c for c in ordered if c.publisher_id == li.publisher_id), fallback)
        out.append(li.model_copy(update={"creative_id": own.creative_id}))
    return out


def build_config(*, brief: Brief, gate: GateResult, publishers: list[PublisherScore],
                 personas: list[PersonaScore], creatives: list[Creative], monthly_usd: float,
                 weak_fit: bool, catalog: Catalog, t: Tuning) -> CampaignConfig:
    if weak_fit:
        monthly_usd = monthly_usd * t.budget.weak_fit_test_fraction
    items, unallocated = allocate(publishers, catalog, monthly_usd, t)
    items = _assign_creatives(items, personas, creatives)
    cpa = target_cpa(brief, publishers, catalog, t)
    subscription = brief.business_model == "subscription"
    bid, cap = t.bid, t.bid.frequency_cap
    order_value = order_value_used(brief, publishers, catalog)

    if personas and brief.age_min is None and brief.age_max is None:
        ages = [(p.age_min, p.age_max) for p in catalog.personas
                if p.id in {s.persona_id for s in personas}]
        age_range = [min(a for a, _ in ages), max(b for _, b in ages)] if ages else [None, None]
    else:
        age_range = [brief.age_min, brief.age_max]
    gender = brief.gender_skew if brief.gender_skew in ("female", "male") else "all"
    interests = _dedup(brief.categories + brief.adjacent_categories)
    cpa_limit = round(cpa * bid.guardrail_cpa_multiple, 2)

    ltv = f" × {bid.subscription_ltv_multiplier:g} subscription LTV" if subscription else ""
    src = "your price" if brief.price_usd else "fit-weighted publisher AOV"
    rationales = {
        "objective": "Conversions: the goal is "
                     + ("subscription starts" if subscription else "purchases"),
        "bid_strategy": f"{bid.cpa_fraction_of_order_value:.0%} of ${order_value:,.0f} order value ({src})"
                        f"{ltv} = ${cpa:,.0f} target CPA",
        "budget": f"${monthly_usd:,.0f}/mo split by fit, capped at each publisher's reach at "
                  f"${t.budget.assumed_cpm_usd:g} CPM"
                  + (f"; ${unallocated:,.0f} unallocated (beyond publisher reach)" if unallocated else "")
                  + (f"; test budget ({t.budget.weak_fit_test_fraction:.0%} of full) because fit is weak"
                     if weak_fit else ""),
        "targeting": f"{len(personas)} personas, interests {', '.join(interests) or 'none'}, "
                     f"ages {age_range[0]}-{age_range[1]}, gender {gender}, US",
        "frequency_cap": f"At most {cap.impressions} impressions per person every {cap.per_days} days",
        "guardrails": f"Pause if CPA exceeds ${cpa_limit:,.0f} ({bid.guardrail_cpa_multiple:g}× target) "
                      f"after {bid.guardrail_min_impressions:,} impressions",
        "line_items": f"{len(items)} publishers, budget share proportional to fit with a "
                      f"{t.budget.min_share:.0%} floor",
    }
    return CampaignConfig(
        campaign_id=_campaign_id(brief, publishers, personas, monthly_usd),
        objective="conversions",
        conversion_event="subscription_start" if subscription else "purchase",
        budget={"monthly_usd": round(monthly_usd, 2), "pacing": "even",
                "unallocated_usd": unallocated, "test_budget": weak_fit},
        bid_strategy={"type": "target_cpa", "target_usd": cpa},
        targeting={"age_range": age_range, "gender": gender, "geo": GEO,
                   "interests": interests, "personas": [p.persona_id for p in personas]},
        line_items=items,
        frequency_cap={"impressions": cap.impressions, "per_days": cap.per_days},
        guardrails={"pause_if_cpa_over_x": bid.guardrail_cpa_multiple, "cpa_limit_usd": cpa_limit,
                    "min_impressions": bid.guardrail_min_impressions},
        rationales=rationales,
        decision_trace={"gate_impl": gate.impl, "gate_confidence": gate.confidence,
                        "gate_threshold": gate.threshold,
                        "publisher_fits": {p.publisher_id: p.fit for p in publishers},
                        "persona_fits": {p.persona_id: p.fit for p in personas},
                        "weak_fit": weak_fit},
    )
