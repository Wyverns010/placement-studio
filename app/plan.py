"""Step 4: the campaign config, every number from code (app/models/tuning.py), and the note reader.

The chain a real ad system needs, kept to one line each: order value -> target CPA -> budget ->
split by fit -> impressions at each publisher's CPM -> projected conversions, revenue and ROAS."""
from __future__ import annotations

import hashlib
import math
import re

from app import rationale
from app.brief import names
from app.constants.llm import MODEL_FAST
from app.constants.plan import (
    AMOUNT,
    AMOUNT_UNITS,
    GEO,
    NOTE_BUDGET,
    NOTE_BUDGET_REFUSED,
    NOTE_DROPPED,
    NOTE_KEEP_ONE,
    NOTE_NOT_NAMED,
    NOTE_NOT_READ,
    NOTE_PACING,
    PACE_WORDS,
)
from app.llm import LLMError, LLMProvider
from app.match import age_bounds
from app.models.ads import Creative
from app.models.brief import Brief
from app.models.catalog import Catalog
from app.models.plan import Budget, CampaignConfig, LineItem, Pacing, PlanChanges
from app.models.scores import PersonaScore, PublisherScore
from app.models.tuning import Tuning
from app.prompts import render, wrap


def order_value(brief: Brief, recommended: list[PublisherScore], catalog: Catalog) -> float:
    """The stated price, or the recommended publishers' average order value weighted by fit."""
    if brief.price_usd:
        return brief.price_usd
    pairs = [(catalog.publisher_by_id[s.publisher_id].avg_order_value_usd, s.fit) for s in recommended] or \
            [(publisher.avg_order_value_usd, 1.0) for publisher in catalog.publishers]
    total = sum(weight for _, weight in pairs)
    return sum(value * weight for value, weight in pairs) / total if total > 0 else pairs[0][0]


def recommended_budget(cpa: float, publishers: int, tuning: Tuning) -> float:
    """Enough for each publisher to reach a month of learning-level conversions at the target CPA,
    rounded up (rounding down would leave too little) and kept within bounds."""
    settings = tuning.budget
    want = cpa * settings.learning_conversions_per_week * settings.weeks_per_month * max(1, publishers)
    return float(min(settings.max_usd, max(settings.min_usd, math.ceil(want / settings.round_to_usd) * settings.round_to_usd)))


def split(recommended: list[PublisherScore], monthly_usd: float, catalog: Catalog, tuning: Tuning) -> list[LineItem]:
    """Each publisher's exact fit share of the budget, to the cent (the total can differ by a cent per
    line item), and the impressions it buys at that publisher's CPM, which follows its audience's income."""
    if not recommended:
        return []
    weights = [score.fit for score in recommended] if sum(s.fit for s in recommended) > 0 else [1.0] * len(recommended)
    items = []
    for score, weight in zip(recommended, weights):
        share = weight / sum(weights)
        amount = round(monthly_usd * share, 2)
        income = catalog.publisher_by_id[score.publisher_id].audience.income_tier
        cpm = tuning.budget.cpm_by_income_usd.get(income, tuning.budget.assumed_cpm_usd)
        items.append(LineItem(publisher_id=score.publisher_id, share=share, budget_usd=amount,
                              cpm_usd=cpm, est_impressions=round(amount / cpm * 1000), ads=[]))
    return items


def _ads_for(publisher_id: str, persona_scores: list[PersonaScore], ads: list[Creative]) -> list[str]:
    """The ads written for this publisher, best persona first, or else the best persona's ad."""
    rank = {score.persona_id: i for i, score in enumerate(persona_scores)}
    ordered = sorted(ads, key=lambda ad: rank.get(ad.persona_id, len(rank)))
    return [ad.persona_id for ad in ordered if ad.publisher_id == publisher_id] or [ad.persona_id for ad in ordered[:1]]


def build_config(brief: Brief, publisher_scores: list[PublisherScore], persona_scores: list[PersonaScore],
                 ads: list[Creative], monthly_usd: float | None, catalog: Catalog, tuning: Tuning,
                 exclude: set[str] = frozenset(), pacing: Pacing | None = None) -> CampaignConfig:
    """The config for the recommended publishers (minus `exclude`). No budget means the recommended
    one; a budget or pacing the user gave always wins."""
    publishers = [score for score in publisher_scores if score.recommended and score.publisher_id not in exclude]
    bid = tuning.bid
    value = order_value(brief, publishers, catalog)
    cpa = float(max(1, round(bid.cpa_fraction_of_order_value * value)))
    recommended_usd = recommended_budget(cpa, len(publishers), tuning)
    source = "recommended" if monthly_usd is None else "user"
    monthly_usd = recommended_usd if monthly_usd is None else monthly_usd
    items = [item.model_copy(update={"ads": _ads_for(item.publisher_id, persona_scores, ads)})
             for item in split(publishers, monthly_usd, catalog, tuning)]
    spend = sum(item.budget_usd for item in items)
    conversions = int(spend / cpa)  # whole conversions the budget fully pays for
    revenue = conversions * round(value)
    cap = tuning.frequency.by_price_tier.get(brief.price_tier) or tuning.frequency.by_price_tier["unknown"]
    bounds = age_bounds(brief, tuning)
    if bounds is None and persona_scores:
        chosen = [catalog.persona_by_id[score.persona_id] for score in persona_scores]
        bounds = (min(p.age_min for p in chosen), max(p.age_max for p in chosen))
    key = "|".join([brief.model_dump_json(), str(monthly_usd), *(i.publisher_id for i in items)])
    slug = re.sub(r"[^a-z0-9]+", "-", (brief.product or "campaign").lower()).strip("-")[:32]
    config = CampaignConfig(
        campaign_id=f"cmp_{slug}_{hashlib.sha1(key.encode()).hexdigest()[:6]}",
        objective="conversions",
        conversion_event="subscription_start" if brief.business_model == "subscription" else "purchase",
        budget=Budget(monthly_usd=round(monthly_usd, 2), recommended_usd=recommended_usd, source=source,
                      pacing=pacing or "even", est_impressions=sum(item.est_impressions for item in items),
                      est_conversions=conversions, est_revenue_usd=float(revenue),
                      est_roas=round(revenue / spend, 2) if spend else 0.0),
        bid_strategy={"type": "target_cpa", "target_usd": cpa},
        targeting={"age_range": list(bounds) if bounds else [None, None],
                   "gender": brief.gender_skew if brief.gender_skew in ("female", "male") else "all",
                   "geo": GEO, "interests": list(dict.fromkeys(brief.categories + brief.adjacent_categories)),
                   "personas": [score.persona_id for score in persona_scores]},
        line_items=items,
        frequency_cap={"impressions": cap.impressions, "per_days": cap.per_days},
        guardrails={"pause_if_cpa_over_x": bid.guardrail_cpa_multiple,
                    "cpa_limit_usd": float(math.floor(cpa * bid.guardrail_cpa_multiple + 0.5)),  # halves up
                    "min_impressions": bid.guardrail_min_impressions},
        rationales={},
    )
    return config.model_copy(update={"rationales": rationale.texts(config, brief, value, publishers, tuning)})


def apply_note(note: str, publisher_scores: list[PublisherScore], llm: LLMProvider,
               tuning: Tuning) -> tuple[float | None, set[str], Pacing | None, list[str]]:
    """One LLM call reads the note into changes; code keeps a budget only if that amount is written in
    the note and within bounds, and drops only publishers the note names (never all of them).
    Returns the budget, dropped publisher ids, pacing and one note per change or refusal."""
    recommended = [score for score in publisher_scores if score.recommended]
    system = render("note_plan", publishers=", ".join(score.name for score in recommended))
    try:
        changes = llm.parse(system=system, user=wrap("user_note", note), schema=PlanChanges, model=MODEL_FAST)
    except LLMError:
        return None, set(), None, [NOTE_NOT_READ]
    notes, settings = list(changes.not_applied), tuning.budget
    written = {round(float(number.replace(",", "")) * AMOUNT_UNITS.get(unit.lower(), 1), 2)
               for number, unit in AMOUNT.findall(note) if number.replace(",", "").replace(".", "", 1).isdigit()}
    budget = changes.budget_usd
    if budget is not None and round(budget, 2) in written and settings.min_usd <= budget <= settings.max_usd:
        notes.append(NOTE_BUDGET.format(usd=budget))
    elif budget is not None:
        notes.append(NOTE_BUDGET_REFUSED.format(usd=budget, low=settings.min_usd, high=settings.max_usd))
        budget = None
    by_name = {score.name.lower(): score for score in recommended}
    dropped = set()
    for name in changes.drop_publishers:
        score = by_name.get(name.lower())
        if score and names(note, score.name):
            dropped.add(score.publisher_id)
            notes.append(NOTE_DROPPED.format(name=score.name))
        elif score:
            notes.append(NOTE_NOT_NAMED.format(name=score.name))
    if recommended and dropped >= {score.publisher_id for score in recommended}:
        dropped = set()
        notes.append(NOTE_KEEP_ONE)
    if changes.pacing:
        notes.append(NOTE_PACING.format(word=PACE_WORDS[changes.pacing].lower()))
    return budget, dropped, changes.pacing, notes
