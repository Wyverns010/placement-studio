"""Plain, explainable publisher scoring: every fit decomposes into 4 visible factors."""
from __future__ import annotations

import math

from app.catalog import Catalog, Persona, Publisher
from app.models import Brief, Factor, PersonaScore, PublisherScore
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
    # a persona-affinity term that tuning maps to this publisher's category (home_decor -> home)
    via = [term for term in b.categories if t.publisher.affinity_parents.get(term) == p.category]
    if via:
        return Factor(name="category", score=cs.same_category, note=f"Same category via {_label(via[0])}"), "same_category"
    adj = sorted((p.tags & set(b.adjacent_categories)) - attrs)
    if adj:
        return Factor(name="category", score=cs.adjacent, note=f"Adjacent: {_label(adj[0])}"), "adjacent"
    shared = sorted(p.tags & (set(b.categories) | set(b.adjacent_categories)) & attrs)
    if shared:
        return Factor(name="category", score=cs.attribute, note=f"Shared attribute: {_label(shared[0])}"), "attribute"
    return Factor(name="category", score=0.0, note="No category overlap"), "none"


def age_bounds(b: Brief, t: Tuning) -> tuple[int, int] | None:
    """The brief's age range with a missing bound filled from tuning ("over 50" -> 50-80);
    None when the brief gives no age at all."""
    if b.age_min is None and b.age_max is None:
        return None
    a = t.audience
    lo = b.age_min if b.age_min is not None else a.age_floor
    hi = b.age_max if b.age_max is not None else a.age_ceiling
    return lo, hi


def _age_overlap(bounds: tuple[int, int] | None, other_min: int, other_max: int,
                 unknown: float) -> float:
    """Share of the brief's age range covered by [other_min, other_max]; `unknown` if the brief has no range."""
    if bounds is None:
        return unknown
    lo, hi = bounds
    if hi <= lo:
        return 1.0 if other_min <= lo <= other_max else 0.0
    return max(0.0, min(hi, other_max) - max(lo, other_min)) / (hi - lo)


def _audience(b: Brief, p: Publisher, t: Tuning) -> tuple[Factor, bool]:
    u = t.publisher.unknown_factor
    bounds = age_bounds(b, t)
    age = _age_overlap(bounds, p.age_min, p.age_max, u)
    split = p.audience.gender_split
    known_gender = b.gender_skew in ("female", "male")
    gender = split.get(b.gender_skew, 0.0) if known_gender else u
    aw = t.publisher.audience_weights
    score = aw.age * age + aw.gender * gender
    unknown = bounds is None and not known_gender
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
    ratio = math.log2(b.price_usd / p.avg_order_value_usd)
    # a product cheaper than the typical basket can sit inside it; one far above it is the real mismatch
    scale = t.publisher.aov_log2_scale if ratio >= 0 else t.publisher.aov_below_log2_scale
    score = max(0.0, 1 - abs(ratio) / scale)
    return Factor(name="aov", score=score, note=f"AOV ${p.avg_order_value_usd:.0f} vs ${b.price_usd:.0f} price"), False


def _pick_reason(factors: list[Factor], unknown: list[bool], recommended: bool) -> Factor:
    """Strongest (recommended) or weakest (excluded) factor, ignoring unknown-placeholder factors."""
    known = [f for f, u in zip(factors, unknown) if not u] or factors[:1]
    return max(known, key=lambda f: f.score) if recommended else min(known, key=lambda f: f.score)


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
        pick = _pick_reason(factors, unk, recommended)
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


# ---- personas ----


def _affinity(b: Brief, p: Persona, t: Tuning) -> Factor:
    sc = t.persona.affinity_scores
    attrs = set(t.publisher.attribute_tags)
    aff = set(p.category_affinities) - attrs
    direct = sorted(aff & set(b.categories))
    if direct:
        return Factor(name="affinity", score=sc.direct, note=f"Affinity: {direct[0]}")
    adj = sorted(aff & set(b.adjacent_categories))
    if adj:
        return Factor(name="affinity", score=sc.adjacent, note=f"Adjacent affinity: {adj[0]}")
    return Factor(name="affinity", score=0.0, note="No affinity overlap")


def _persona_price(b: Brief, p: Persona, t: Tuning) -> Factor:
    ideal = t.persona.price_ideal.get(b.price_tier)
    if ideal is None:
        return Factor(name="price", score=t.publisher.unknown_factor, note="Price tier unknown")
    score = max(0.0, 1 - abs(ideal - p.price_rank) / t.persona.price_scale)
    sens = p.price_sensitivity
    return Factor(name="price", score=score, note=f"{sens.capitalize()} price sensitivity vs {b.price_tier}")


def _persona_age(b: Brief, p: Persona, t: Tuning) -> Factor:
    bounds = age_bounds(b, t)
    score = _age_overlap(bounds, p.age_min, p.age_max, t.publisher.unknown_factor)
    note = ("Brief ages unknown" if bounds is None
            else f"Ages {p.age_min}\u2013{p.age_max} vs {bounds[0]}\u2013{bounds[1]}")
    return Factor(name="age", score=score, note=note)


def _persona_raw(b: Brief, p: Persona, t: Tuning) -> tuple[float, list[Factor]]:
    """Unclamped fit and its factors (a 4th `conflict` factor only when a penalty applies)."""
    w = t.persona.weights
    aff, price, age = _affinity(b, p, t), _persona_price(b, p, t), _persona_age(b, p, t)
    factors = [aff, price, age]
    raw = w.affinity * aff.score + w.price * price.score + w.age * age.score
    hit = sorted({c.lower() for c in b.conflicts} & {d.lower() for d in p.disinterested_in})
    if hit:
        pen = t.persona.conflict_penalty
        raw -= pen
        factors.append(Factor(name="conflict", score=-pen, note=f"Conflicts: {hit[0]}"))
    return raw, factors


def score_personas(brief: Brief, catalog: Catalog, t: Tuning) -> list[PersonaScore]:
    rows = []
    for p in catalog.personas:
        raw, factors = _persona_raw(brief, p, t)
        rows.append((max(0.0, min(1.0, raw)), p, factors))
    rows.sort(key=lambda r: (-r[0], r[1].id))
    return [PersonaScore(persona_id=p.id, name=p.name, fit=round(fit, 3), factors=f, stretch=False)
            for fit, p, f in rows]


def select_personas(scores: list[PersonaScore], t: Tuning) -> list[PersonaScore]:
    """Scores must be sorted best-first. Qualifiers (>= cutoff, up to max), else stretch-fill up to min."""
    pt = t.persona
    chosen = [s.model_copy(update={"stretch": False}) for s in scores if s.fit >= pt.cutoff][: pt.max]
    if len(chosen) < pt.min:
        rest = [s for s in scores if s.fit < pt.cutoff][: pt.min - len(chosen)]
        chosen += [s.model_copy(update={"stretch": True}) for s in rest]
    return chosen
