"""Budget economics in code: reach caps, allocation, target CPA, the recommended monthly
budget, frequency cap and pacing. Every number comes from config/tuning.yaml."""
from __future__ import annotations

import math
from typing import Literal, NamedTuple

from app.catalog import Catalog, Publisher
from app.models import Brief, LineItem, PublisherScore
from app.tuning import Tuning


def cpm_usd(pub: Publisher, t: Tuning) -> float:
    """What 1,000 impressions cost on this publisher: by its audience's income tier."""
    return t.budget.cpm_by_income_usd.get(pub.audience.income_tier, t.budget.assumed_cpm_usd)


def reach_cap_usd(pub: Publisher, t: Tuning) -> float:
    """Most one campaign can spend on a publisher in a month: its share of the impressions."""
    return pub.monthly_impressions * t.budget.max_share_of_impressions / 1000 * cpm_usd(pub, t)


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
    caps = [reach_cap_usd(catalog.publisher(p.publisher_id), t) for p in recommended]
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
    items = []
    for p, s in zip(recommended, spend):
        cpm = cpm_usd(catalog.publisher(p.publisher_id), t)
        items.append(LineItem(publisher_id=p.publisher_id, share=(s / total if total else 0.0),
                              budget_usd=round(s, 2), creative_id=None, cpm_usd=cpm,
                              est_impressions=int(s / cpm * 1000) if cpm else 0))
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
    per_publisher: list[float]  # min(reach cap, target CPA x monthly conversions) per publisher
    cpa: float
    capped: list[str]  # publisher ids whose reach cap is below what the conversion goal needs


def _round_to(x: float, unit: float) -> float:
    return math.floor(x / unit + 0.5) * unit


def weak_fit_test_usd(full_usd: float, t: Tuning) -> float:
    """min(test fraction x full recommendation, test cap), rounded, never below min_usd."""
    b = t.budget
    raw = min(full_usd * b.weak_fit_test_fraction, b.weak_fit_test_max_usd)
    return max(b.min_usd, _round_to(raw, b.round_to_usd))


def recommended_budget(brief: Brief, publishers: list[PublisherScore], catalog: Catalog,
                       weak_fit: bool, t: Tuning) -> Recommendation:
    """Enough for each line item to reach a month of learning-level conversions (per week x weeks) at
    the target CPA, capped at its reach; rounded up, clamped to the budget bounds; a weak fit gets a capped test share of that."""
    b = t.budget
    cpa = target_cpa(brief, publishers, catalog, t)
    want = cpa * b.conversions_per_month
    caps = {p.publisher_id: reach_cap_usd(catalog.publisher(p.publisher_id), t) for p in publishers}
    parts = [min(caps[p.publisher_id], want) for p in publishers]
    # rounded up: rounding down would leave too little for the conversions the bid needs
    full = min(b.max_usd, max(b.min_usd, math.ceil(sum(parts) / b.round_to_usd) * b.round_to_usd))
    usd = weak_fit_test_usd(full, t) if weak_fit else full
    return Recommendation(usd=float(usd), full_usd=float(full), per_publisher=parts, cpa=cpa,
                          capped=[i for i, c in caps.items() if c < want])


class Projection(NamedTuple):
    """What the budget should buy at the target CPA: plain arithmetic on the line items."""
    impressions: int
    conversions: int
    revenue_usd: float
    roas: float  # revenue / spend
    conversions_per_1k: float  # what the target CPA needs, per 1,000 impressions (blended)
    stretch: bool  # above max_conversions_per_1k_impressions: the CPA is optimistic


def projection(items: list[LineItem], cpa: float, order_value: float, t: Tuning) -> Projection:
    spend = sum(li.budget_usd for li in items)
    imps = sum(li.est_impressions for li in items)
    conv = spend / cpa if cpa else 0.0
    per_1k = conv / imps * 1000 if imps else 0.0
    revenue = conv * order_value
    return Projection(impressions=imps, conversions=int(conv), revenue_usd=round(revenue, 2),
                      roas=round(revenue / spend, 2) if spend else 0.0,
                      conversions_per_1k=round(per_1k, 2),
                      stretch=per_1k > t.budget.max_conversions_per_1k_impressions)


def frequency_cap(brief: Brief, weak_fit: bool, t: Tuning) -> tuple[int, int]:
    """(impressions, per_days): by price tier, +extra for a subscription; a weak-fit test shows
    one fewer over a window of at most weak_fit_max_per_days (a short test, front-loaded)."""
    f = t.frequency
    base = f.by_price_tier.get(brief.price_tier) or f.by_price_tier["unknown"]
    n, days = base.impressions, base.per_days
    if brief.business_model == "subscription":
        n += f.subscription_extra
    if weak_fit:
        n -= f.weak_fit_reduction
        days = min(days, f.weak_fit_max_per_days)
    return max(f.min_impressions, n), days


Pacing = Literal["front_loaded", "even", "accelerated"]


def pacing(brief: Brief, weak_fit: bool, monthly_usd: float, recommended_usd: float) -> Pacing:
    """front_loaded for a weak-fit test (learn fast); accelerated for value/mid buys when the budget
    is below the recommendation (spend it while it converts); otherwise even."""
    if weak_fit:
        return "front_loaded"
    if brief.price_tier in ("value", "mid") and monthly_usd < recommended_usd:
        return "accelerated"
    return "even"
