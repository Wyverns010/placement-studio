"""Budget economics in code: reach caps, allocation, target CPA, the recommended monthly
budget, frequency cap and pacing. Every number comes from config/tuning.yaml."""
from __future__ import annotations

import math
from typing import Literal, NamedTuple

from app.catalog import Catalog
from app.models import Brief, LineItem, PublisherScore
from app.tuning import Tuning


def reach_cap_usd(impressions: int, t: Tuning) -> float:
    """Most a publisher can absorb per month at the assumed CPM."""
    return impressions / 1000 * t.budget.assumed_cpm_usd


def _weights(fits: list[float], t: Tuning) -> list[float]:
    """Fit-proportional shares with every publisher floored at min_share (sum to 1)."""
    n = len(fits)
    floor = t.budget.min_share
    if n * floor > 1 or sum(fits) <= 0:
        return [1 / n] * n
    pinned: set[int] = set()
    while True:
        free = [i for i in range(n) if i not in pinned]
        room = 1 - floor * len(pinned)
        total = sum(fits[i] for i in free)
        shares = {i: floor for i in pinned}
        shares.update({i: room * fits[i] / total for i in free} if total > 0
                      else {i: room / len(free) for i in free})
        newly = {i for i in free if shares[i] < floor}
        if not newly:
            return [shares[i] for i in range(n)]
        pinned |= newly


def allocate(recommended: list[PublisherScore], catalog: Catalog, monthly_usd: float,
             t: Tuning) -> tuple[list[LineItem], float]:
    """Water-fill the budget by fit, capping each publisher at its reach. Pure numbers, no text."""
    if not recommended:
        return [], monthly_usd
    caps = [reach_cap_usd(catalog.publisher(p.publisher_id).monthly_impressions, t) for p in recommended]
    weights = _weights([p.fit for p in recommended], t)
    spend = [0.0] * len(recommended)
    active = list(range(len(recommended)))
    remaining = monthly_usd
    while active:
        wsum = sum(weights[i] for i in active)
        proposed = {i: remaining * weights[i] / wsum for i in active}
        capped = [i for i in active if proposed[i] > caps[i]]
        if not capped:
            for i in active:
                spend[i] = proposed[i]
            break
        for i in capped:
            spend[i] = caps[i]
            remaining -= caps[i]
        active = [i for i in active if i not in capped]
    total = sum(spend)
    items = [
        LineItem(publisher_id=p.publisher_id, share=(s / total if total else 0.0),
                 budget_usd=round(s, 2), creative_id=None)
        for p, s in zip(recommended, spend)
    ]
    return items, round(max(0.0, monthly_usd - total), 2)


def target_cpa(brief: Brief, recommended: list[PublisherScore], catalog: Catalog, t: Tuning) -> float:
    """cpa_fraction x order value (x LTV multiplier for subscriptions), whole dollars."""
    order_value = order_value_used(brief, recommended, catalog)
    mult = t.bid.subscription_ltv_multiplier if brief.business_model == "subscription" else 1
    return float(round(t.bid.cpa_fraction_of_order_value * order_value * mult))


def order_value_used(brief: Brief, recommended: list[PublisherScore], catalog: Catalog) -> float:
    return brief.price_usd or _weighted_aov(recommended, catalog)


def _weighted_aov(recommended: list[PublisherScore], catalog: Catalog) -> float:
    pubs = [(catalog.publisher(p.publisher_id).avg_order_value_usd, p.fit) for p in recommended]
    if not pubs:
        pubs = [(p.avg_order_value_usd, 1.0) for p in catalog.publishers]
    total = sum(w for _, w in pubs)
    if total <= 0:
        return sum(a for a, _ in pubs) / len(pubs)
    return sum(a * w for a, w in pubs) / total


class Recommendation(NamedTuple):
    """The recommended monthly budget and the inputs that produced it."""
    usd: float  # what we recommend (the weak-fit test share when fit is weak)
    full_usd: float  # rounded and clamped sum, before any weak-fit test share
    per_publisher: list[float]  # min(reach cap, target CPA x conversions) per publisher
    cpa: float


def _round_to(x: float, unit: float) -> float:
    return math.floor(x / unit + 0.5) * unit


def recommended_budget(brief: Brief, publishers: list[PublisherScore], catalog: Catalog,
                       weak_fit: bool, t: Tuning) -> Recommendation:
    """Enough for each line item to reach `conversions_per_line_item` at the target CPA, capped at
    its reach; rounded, clamped to the budget bounds; a weak fit gets the test share of that."""
    b = t.budget
    cpa = target_cpa(brief, publishers, catalog, t)
    want = cpa * b.conversions_per_line_item
    parts = [min(reach_cap_usd(catalog.publisher(p.publisher_id).monthly_impressions, t), want)
             for p in publishers]
    full = min(b.max_usd, max(b.min_usd, _round_to(sum(parts), b.round_to_usd)))
    usd = max(b.min_usd, full * b.weak_fit_test_fraction) if weak_fit else full
    return Recommendation(usd=float(usd), full_usd=float(full), per_publisher=parts, cpa=cpa)


def frequency_cap(brief: Brief, weak_fit: bool, t: Tuning) -> tuple[int, int]:
    """(impressions, per_days): by price tier, +extra for a subscription, -reduction for a test."""
    f = t.frequency
    base = f.by_price_tier.get(brief.price_tier) or f.by_price_tier["unknown"]
    n = base.impressions
    if brief.business_model == "subscription":
        n += f.subscription_extra
    if weak_fit:
        n -= f.weak_fit_reduction
    return max(f.min_impressions, n), base.per_days


Pacing = Literal["front_loaded", "even", "accelerated"]


def pacing(brief: Brief, weak_fit: bool, monthly_usd: float, recommended_usd: float) -> Pacing:
    """front_loaded for a weak-fit test (learn fast); accelerated for value/mid buys when the budget
    is below the recommendation (spend it while it converts); otherwise even."""
    if weak_fit:
        return "front_loaded"
    if brief.price_tier in ("value", "mid") and monthly_usd < recommended_usd:
        return "accelerated"
    return "even"
