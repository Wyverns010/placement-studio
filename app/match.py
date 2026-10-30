"""Plain, explainable publisher scoring: every fit decomposes into 4 visible factors."""
from __future__ import annotations

import math

from app.catalog import Catalog, Publisher
from app.models import Brief, Factor, PublisherScore
from app.tuning import Tuning

_INCOME_NAME = {1: "mid", 2: "mid-high", 3: "high"}


def _label(s: str) -> str:
    return s.replace("_", " ")


def _category(b: Brief, p: Publisher, t: Tuning, catalog: Catalog) -> tuple[Factor, str]:
    cs = t.publisher.category_scores
    attrs = set(t.publisher.attribute_tags)
    if p.category in b.categories:
        return Factor(name="category", score=cs.primary, note=f"{_label(p.category).capitalize()} category match"), "primary"
    sub = [c for c in p.subcategories if c in b.categories and c not in attrs]
    if sub:
        return Factor(name="category", score=cs.subcategory, note=f"{_label(sub[0]).capitalize()} subcategory match"), "subcategory"
    # parent category of a brief term: some publisher lists the term as a subcategory under p.category
    parents = {q.category for term in b.categories if term not in attrs
               for q in catalog.publishers if term in q.subcategories}
    if p.category in parents:
        return Factor(name="category", score=cs.same_category, note=f"Same category: {_label(p.category)}"), "same_category"
    adj = sorted((p.tags & set(b.adjacent_categories)) - attrs)
    if adj:
        return Factor(name="category", score=cs.adjacent, note=f"Adjacent: {_label(adj[0])}"), "adjacent"
    shared = sorted(p.tags & (set(b.categories) | set(b.adjacent_categories)) & attrs)
    if shared:
        return Factor(name="category", score=cs.attribute, note=f"Shared attribute: {_label(shared[0])}"), "attribute"
    return Factor(name="category", score=0.0, note="No category overlap"), "none"


def _audience(b: Brief, p: Publisher, t: Tuning) -> tuple[Factor, bool]:
    u = t.publisher.unknown_factor
    lo, hi = b.age_min, b.age_max
    if lo is None or hi is None:
        age = u
    elif hi <= lo:
        age = 1.0 if p.age_min <= lo <= p.age_max else 0.0
    else:
        age = max(0.0, min(hi, p.age_max) - max(lo, p.age_min)) / (hi - lo)
    split = p.audience.gender_split
    if b.gender_skew == "female":
        gender = split.get("female", 0.0)
    elif b.gender_skew == "male":
        gender = split.get("male", 0.0)
    else:
        gender = u
    aw = t.publisher.audience_weights
    score = aw.age * age + aw.gender * gender
    unknown = lo is None or hi is None
    unknown = unknown and b.gender_skew not in ("female", "male")
    top = "female" if split.get("female", 0) >= split.get("male", 0) else "male"
    share = round(split.get(top, 0.0) * 100)
    who = "women" if top == "female" else "men"
    return Factor(name="audience", score=score, note=f"Skews {p.audience.age_skew}, {share}% {who}"), unknown


def _income(b: Brief, p: Publisher, t: Tuning) -> tuple[Factor, bool]:
    target = t.publisher.income_targets.get(b.price_tier)
    if target is None:
        return Factor(name="income", score=t.publisher.unknown_factor, note="Price tier unknown"), True
    note = f"Income tier {_INCOME_NAME[p.income_rank]} vs {b.price_tier}"
    score = max(0.0, 1 - abs(p.income_rank - target) / t.publisher.income_scale)
    return Factor(name="income", score=score, note=note), False


def _aov(b: Brief, p: Publisher, t: Tuning) -> tuple[Factor, bool]:
    if b.price_usd is None or b.price_usd <= 0:
        return Factor(name="aov", score=t.publisher.unknown_factor, note="Price unknown"), True
    score = max(0.0, 1 - abs(math.log2(b.price_usd / p.avg_order_value_usd)) / t.publisher.aov_log2_scale)
    return Factor(name="aov", score=score, note=f"AOV ${p.avg_order_value_usd:.0f} vs ${b.price_usd:.0f} price"), False


def score_publishers(brief: Brief, catalog: Catalog, t: Tuning) -> list[PublisherScore]:
    pt = t.publisher
    w = pt.weights
    weights = {"category": w.category, "audience": w.audience, "income": w.income, "aov": w.aov}
    rows: list[tuple[float, Publisher, list[Factor], list[bool]]] = []
    for p in catalog.publishers:
        cat, level = _category(brief, p, t, catalog)
        aud, aud_unk = _audience(brief, p, t)
        inc, inc_unk = _income(brief, p, t)
        aov, aov_unk = _aov(brief, p, t)
        factors = [cat, aud, inc, aov]
        fit = sum(weights[f.name] * f.score for f in factors)
        if level in ("attribute", "none"):
            fit *= pt.no_category_penalty
        if not aov_unk:
            fit *= pt.aov_gate_floor + (1 - pt.aov_gate_floor) * aov.score
        rows.append((fit, p, factors, [False, aud_unk, inc_unk, aov_unk]))
    rows.sort(key=lambda r: (-r[0], r[1].id))
    out: list[PublisherScore] = []
    for rank, (fit, p, factors, unk) in enumerate(rows):
        recommended = fit >= pt.cutoff and rank < pt.max_recommended
        if recommended:
            known = [f for f, u in zip(factors, unk) if not u] or factors[:1]
            pick = max(known, key=lambda f: f.score)
        else:
            pick = min(factors, key=lambda f: f.score)
        out.append(PublisherScore(
            publisher_id=p.id, name=p.name, fit=round(fit, 3), factors=factors,
            recommended=recommended, stretch=False, reason=pick.note,
        ))
    return out


def is_weak_fit(scores: list[PublisherScore], t: Tuning) -> bool:
    return sum(1 for s in scores if s.recommended) < t.publisher.weak_fit_min_recommended


def mark_stretch(scores: list[PublisherScore], t: Tuning) -> list[PublisherScore]:
    n = t.publisher.weak_fit_show
    return [
        s.model_copy(update={"recommended": i < n, "stretch": i < n})
        for i, s in enumerate(scores)
    ]
