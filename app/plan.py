"""Step 4: the campaign config, all numbers from code (config/tuning.yaml), and the note reader."""
from __future__ import annotations

import hashlib
import math
import re

from app import rationale
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
from app.models.plan import (
    Budget,
    CampaignConfig,
    LineItem,
    Pacing,
    PlanChanges,
    Recommendation,
)
from app.models.scores import PersonaScore, PublisherScore
from app.models.tuning import Tuning
from app.prompts import render, wrap


def publisher_prices(publisher_ids: list[str], catalog: Catalog, tuning: Tuning) -> dict[str, tuple[float, float]]:
    """Id -> (CPM by the audience's income, reach cap: the most one campaign can spend there a month)."""
    settings = tuning.budget
    prices = {}
    for publisher_id in publisher_ids:
        publisher = catalog.publisher_by_id[publisher_id]
        cpm = settings.cpm_by_income_usd.get(publisher.audience.income_tier, settings.assumed_cpm_usd)
        prices[publisher_id] = cpm, publisher.monthly_impressions * settings.max_share_of_impressions / 1000 * cpm
    return prices


def order_value(brief: Brief, recommended: list[PublisherScore], catalog: Catalog) -> float:
    """The stated price, or the recommended publishers' average order value weighted by fit."""
    if brief.price_usd:
        return brief.price_usd
    pairs = [(catalog.publisher_by_id[score.publisher_id].avg_order_value_usd, score.fit) for score in recommended]
    if not pairs:
        pairs = [(publisher.avg_order_value_usd, 1.0) for publisher in catalog.publishers]
    total = sum(weight for _, weight in pairs)
    if total <= 0:
        return sum(value for value, _ in pairs) / len(pairs)
    return sum(value * weight for value, weight in pairs) / total


def recommended_budget(brief: Brief, recommended: list[PublisherScore], prices: dict[str, tuple[float, float]],
                       catalog: Catalog, weak_fit: bool, tuning: Tuning) -> Recommendation:
    """Enough for each publisher to reach a month of learning-level conversions at the target CPA,
    capped at its reach; rounded up and kept within bounds. A weak fit gets a capped test share."""
    settings, bid = tuning.budget, tuning.bid
    multiplier = bid.subscription_ltv_multiplier if brief.business_model == "subscription" else 1
    cpa = float(round(bid.cpa_fraction_of_order_value * order_value(brief, recommended, catalog) * multiplier))
    want = cpa * settings.learning_conversions_per_week * settings.weeks_per_month
    parts = [min(prices[score.publisher_id][1], want) for score in recommended]
    # rounded up: rounding down would leave too little for the conversions the bid needs
    full = min(settings.max_usd, max(settings.min_usd, math.ceil(sum(parts) / settings.round_to_usd) * settings.round_to_usd))
    usd = full
    if weak_fit:
        test = min(full * settings.weak_fit_test_fraction, settings.weak_fit_test_max_usd)
        usd = max(settings.min_usd, math.floor(test / settings.round_to_usd + 0.5) * settings.round_to_usd)
    capped = [score.publisher_id for score in recommended if prices[score.publisher_id][1] < want]
    return Recommendation(usd=float(usd), full_usd=float(full), cpa=cpa, capped=capped)


def _fit_shares(fits: list[float], min_share: float) -> list[float]:
    """Fit-proportional shares with every publisher floored at min_share (they sum to 1)."""
    count = len(fits)
    if count * min_share > 1 or sum(fits) <= 0:
        return [1 / count] * count
    pinned: set[int] = set()
    while True:
        free = [i for i in range(count) if i not in pinned]
        room = 1 - min_share * len(pinned)
        total = sum(fits[i] for i in free)
        shares = {i: min_share for i in pinned}
        shares.update({i: room * fits[i] / total for i in free} if total > 0 else {i: room / len(free) for i in free})
        below = {i for i in free if shares[i] < min_share}
        if not below:
            return [shares[i] for i in range(count)]
        pinned |= below


def _whole_dollars(amounts: list[float]) -> list[float]:
    """Each amount in whole dollars, keeping the total (the largest remainders get the extra dollar)."""
    floors = [math.floor(amount) for amount in amounts]
    short = round(sum(amounts)) - sum(floors)
    by_remainder = sorted(range(len(amounts)), key=lambda i: amounts[i] - floors[i], reverse=True)
    for i in by_remainder[:max(0, short)]:
        floors[i] += 1
    return [float(amount) for amount in floors]


def allocate(recommended: list[PublisherScore], monthly_usd: float, prices: dict[str, tuple[float, float]],
             tuning: Tuning) -> tuple[list[LineItem], float]:
    """Water-fill the budget by fit, capping each publisher at its reach; returns the line items and
    what's left over."""
    if not recommended:
        return [], monthly_usd
    caps = [prices[score.publisher_id][1] for score in recommended]
    shares = _fit_shares([score.fit for score in recommended], tuning.budget.min_share)
    spend = [0.0] * len(recommended)
    active, remaining = list(range(len(recommended))), monthly_usd
    while active:
        share_total = sum(shares[i] for i in active)
        proposed = {i: remaining * shares[i] / share_total for i in active}
        capped = [i for i in active if proposed[i] > caps[i]]
        if not capped:
            for i in active:
                spend[i] = proposed[i]
            break
        for i in capped:
            spend[i] = caps[i]
            remaining -= caps[i]
        active = [i for i in active if i not in capped]
    spend = _whole_dollars(spend)
    total = sum(spend)
    items = []
    for score, amount in zip(recommended, spend):
        cpm = prices[score.publisher_id][0]
        items.append(LineItem(publisher_id=score.publisher_id, share=amount / total if total else 0.0,
                              budget_usd=round(amount, 2), cpm_usd=cpm,
                              est_impressions=round(amount / cpm * 1000) if cpm else 0, ads=[]))
    return items, round(max(0.0, monthly_usd - total), 2)


def frequency_cap(brief: Brief, weak_fit: bool, tuning: Tuning) -> tuple[int, int]:
    """(impressions, per_days) by price tier, +1 for a subscription; a weak-fit test shows one fewer
    over a window of at most weak_fit_max_per_days."""
    settings = tuning.frequency
    base = settings.by_price_tier.get(brief.price_tier) or settings.by_price_tier["unknown"]
    impressions, days = base.impressions, base.per_days
    if brief.business_model == "subscription":
        impressions += settings.subscription_extra
    if weak_fit:
        impressions -= settings.weak_fit_reduction
        days = min(days, settings.weak_fit_max_per_days)
    return max(settings.min_impressions, impressions), days


def choose_pacing(brief: Brief, weak_fit: bool, monthly_usd: float, recommended_usd: float) -> Pacing:
    """Front-loaded for a weak-fit test (learn fast); accelerated for value/mid buys below the
    recommendation (spend it while it converts); otherwise even."""
    if weak_fit:
        return "front_loaded"
    if brief.price_tier in ("value", "mid") and monthly_usd < recommended_usd:
        return "accelerated"
    return "even"


def _campaign_id(brief: Brief, publisher_ids: list[str], persona_ids: list[str], monthly_usd: float) -> str:
    key = "|".join([brief.model_dump_json(), str(monthly_usd), ",".join(publisher_ids), ",".join(persona_ids)])
    slug = re.sub(r"[^a-z0-9]+", "-", (brief.product or "campaign").lower()).strip("-")[:32]
    return f"cmp_{slug}_{hashlib.sha1(key.encode()).hexdigest()[:6]}"


def _assign_ads(items: list[LineItem], persona_scores: list[PersonaScore], ads: list[Creative]) -> list[LineItem]:
    """Each line item serves the ads written for its publisher (the first is primary, the rest rotate),
    or else the best persona's ad."""
    if not ads:
        return items
    rank = {score.persona_id: i for i, score in enumerate(persona_scores)}
    ordered = sorted(ads, key=lambda ad: rank.get(ad.persona_id, len(rank)))
    best = max(persona_scores, key=lambda score: score.fit).persona_id if persona_scores else None
    fallback = next((ad for ad in ordered if ad.persona_id == best), ordered[0])
    return [item.model_copy(update={"ads": [ad.persona_id for ad in ordered if ad.publisher_id == item.publisher_id]
                                    or [fallback.persona_id]}) for item in items]


def build_config(brief: Brief, publisher_scores: list[PublisherScore], persona_scores: list[PersonaScore],
                 ads: list[Creative], monthly_usd: float | None, catalog: Catalog, tuning: Tuning,
                 exclude: set[str] = frozenset(), pacing: Pacing | None = None) -> CampaignConfig:
    """The config for the recommended publishers (minus `exclude`). No budget means the recommended
    one; a budget or pacing the user gave always wins."""
    publishers = [score for score in publisher_scores if score.recommended and score.publisher_id not in exclude]
    weak_fit = any(score.recommended and score.stretch for score in publisher_scores)
    prices = publisher_prices([score.publisher_id for score in publishers], catalog, tuning)
    recommendation = recommended_budget(brief, publishers, prices, catalog, weak_fit, tuning)
    source = "recommended" if monthly_usd is None else "user"
    monthly_usd = recommendation.usd if monthly_usd is None else monthly_usd
    items, unallocated = allocate(publishers, monthly_usd, prices, tuning)
    items = _assign_ads(items, persona_scores, ads)
    cpa, bid = recommendation.cpa, tuning.bid
    subscription = brief.business_model == "subscription"
    per_order = order_value(brief, publishers, catalog)
    value = per_order * (bid.subscription_ltv_multiplier if subscription else 1)
    spend = sum(item.budget_usd for item in items)
    impressions = sum(item.est_impressions for item in items)
    conversions = int(spend / cpa) if cpa else 0  # whole conversions, as shown
    per_1k = conversions / impressions * 1000 if impressions else 0.0
    revenue = conversions * round(value)  # whole-dollar value, as shown
    impressions_cap, per_days = frequency_cap(brief, weak_fit, tuning)
    code_pacing = choose_pacing(brief, weak_fit, monthly_usd, recommendation.usd)
    bounds = age_bounds(brief, tuning)
    if bounds is not None:
        age_range = list(bounds)
    elif persona_scores:
        chosen = [catalog.persona_by_id[score.persona_id] for score in persona_scores]
        age_range = [min(persona.age_min for persona in chosen), max(persona.age_max for persona in chosen)]
    else:
        age_range = [None, None]
    config = CampaignConfig(
        campaign_id=_campaign_id(brief, [s.publisher_id for s in publishers], [s.persona_id for s in persona_scores],
                                 monthly_usd),
        objective="conversions",
        conversion_event="subscription_start" if subscription else "purchase",
        budget=Budget(monthly_usd=round(monthly_usd, 2), recommended_usd=recommendation.usd, source=source,
                      pacing=pacing or code_pacing, unallocated_usd=unallocated,
                      test_budget=weak_fit and source == "recommended", est_impressions=impressions,
                      est_conversions=conversions, est_revenue_usd=float(revenue),
                      est_roas=round(revenue / spend, 2) if spend else 0.0, conversions_per_1k=round(per_1k, 2),
                      cpa_is_stretch=per_1k > tuning.budget.max_conversions_per_1k_impressions),
        bid_strategy={"type": "target_cpa", "target_usd": cpa},
        targeting={"age_range": age_range,
                   "gender": brief.gender_skew if brief.gender_skew in ("female", "male") else "all",
                   "geo": GEO, "interests": list(dict.fromkeys(brief.categories + brief.adjacent_categories)),
                   "personas": [score.persona_id for score in persona_scores]},
        line_items=items,
        frequency_cap={"impressions": impressions_cap, "per_days": per_days},
        guardrails={"pause_if_cpa_over_x": bid.guardrail_cpa_multiple,
                    "cpa_limit_usd": float(math.floor(cpa * bid.guardrail_cpa_multiple + 0.5)),
                    "min_impressions": bid.guardrail_min_impressions},
        rationales={},
    )
    texts = rationale.texts(config, brief, recommendation, per_order, weak_fit, code_pacing, publishers, persona_scores,
                            ads, prices, catalog, tuning)
    return config.model_copy(update={"rationales": texts})


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
    text, notes, settings = note.lower(), list(changes.not_applied), tuning.budget
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
        if score and re.search(rf"\b{re.escape(score.name.lower())}\b", text):
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
