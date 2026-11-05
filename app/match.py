"""Steps 1–2: publisher and persona fit. Every fit is a weighted sum of visible factors."""
from __future__ import annotations

import math

from app.models.brief import Brief
from app.models.catalog import Catalog, Persona, Publisher
from app.models.scores import Factor, PersonaScore, PublisherScore
from app.models.tuning import Tuning

INCOME_NAMES = {1: "mid", 2: "mid-high", 3: "high"}
EXCLUDED_REASON = "Excluded by your note"


# ---- shared ----

def scoped(brief: Brief, catalog: Catalog, tuning: Tuning) -> Brief:
    """The brief without scoped words whose category it doesn't otherwise name ("toys" for kids'
    toys is not a pet store's toys)."""
    words = set(brief.categories) | set(brief.adjacent_categories)
    kept = set()
    for word in words:
        parent = tuning.publisher.scoped_terms.get(word)
        if parent is None or (words - {word}) & ({parent} | set(catalog.vocab_groups.get(parent, []))):
            kept.add(word)
    if kept == words:
        return brief
    return brief.model_copy(update={"categories": [c for c in brief.categories if c in kept],
                                    "adjacent_categories": [c for c in brief.adjacent_categories if c in kept]})


def term_parents(catalog: Catalog, tuning: Tuning) -> dict[str, set[str]]:
    """Category word -> the publisher categories it sits under (catalog groups + affinity_parents)."""
    attributes = set(tuning.publisher.attribute_tags)
    parents: dict[str, set[str]] = {}
    for category, words in catalog.vocab_groups.items():
        for word in words:
            if word not in attributes and word != category:
                parents.setdefault(word, set()).add(category)
    for word, parent in tuning.publisher.affinity_parents.items():
        parents.setdefault(word, set()).add(parent)
    return parents


def age_bounds(brief: Brief, tuning: Tuning) -> tuple[int, int] | None:
    """The brief's ages with a missing end filled in ("over 50" -> 50-80); None when it gives none."""
    if brief.age_min is None and brief.age_max is None:
        return None
    low = brief.age_min if brief.age_min is not None else tuning.input.age_floor
    high = brief.age_max if brief.age_max is not None else tuning.input.age_ceiling
    return low, high


def age_overlap(bounds: tuple[int, int] | None, low: int, high: int, unknown: float) -> float:
    """Share of the brief's age range covered by [low, high]; `unknown` if the brief has no range."""
    if bounds is None:
        return unknown
    brief_low, brief_high = bounds
    if brief_high <= brief_low:
        return 1.0 if low <= brief_low <= high else 0.0
    return max(0.0, min(brief_high, high) - max(brief_low, low)) / (brief_high - brief_low)


# ---- publishers ----

def _category(brief: Brief, publisher: Publisher, catalog: Catalog, tuning: Tuning) -> tuple[Factor, str]:
    """The category factor and its level: primary, subcategory, same_category, adjacent, attribute, none."""
    scores = tuning.publisher.category_scores
    attributes = set(tuning.publisher.attribute_tags)
    label = publisher.category.replace("_", " ")
    if publisher.category in brief.categories:
        # the brief also names a narrower word in this category (kitchen) that this publisher lacks
        narrow = sorted(set(brief.categories) & set(catalog.vocab_groups.get(publisher.category, []))
                        - attributes - set(publisher.subcategories) - {publisher.category})
        if narrow and not set(brief.categories) & set(publisher.subcategories):
            note = f"{label.capitalize()} category, but no {narrow[0].replace('_', ' ')}"
            return Factor(name="category", score=scores["same_category"], note=note), "same_category"
        note = f"{label.capitalize()} category match"
        return Factor(name="category", score=scores["primary"], note=note), "primary"
    sub = [word for word in publisher.subcategories if word in brief.categories and word not in attributes]
    if sub:
        note = f"{sub[0].replace('_', ' ').capitalize()} subcategory match"
        return Factor(name="category", score=scores["subcategory"], note=note), "subcategory"
    # parent category of a brief word: some publisher lists the word as a subcategory under this category
    parents = {other.category for word in brief.categories if word not in attributes
               for other in catalog.publishers if word in other.subcategories}
    if publisher.category in parents:
        return Factor(name="category", score=scores["same_category"], note=f"Same category: {label}"), "same_category"
    # a persona-affinity word that tuning maps to this publisher's category (home_decor -> home)
    via = [word for word in brief.categories if tuning.publisher.affinity_parents.get(word) == publisher.category]
    if via:
        note = f"Same category via {via[0].replace('_', ' ')}"
        return Factor(name="category", score=scores["same_category"], note=note), "same_category"
    adjacent = sorted((publisher.tags & set(brief.adjacent_categories)) - attributes)
    if adjacent:
        note = f"Adjacent: {adjacent[0].replace('_', ' ')}"
        return Factor(name="category", score=scores["adjacent"], note=note), "adjacent"
    via = [word for word in brief.adjacent_categories
           if tuning.publisher.affinity_parents.get(word) == publisher.category]
    if via:
        note = f"Adjacent via {via[0].replace('_', ' ')}"
        return Factor(name="category", score=scores["adjacent"], note=note), "adjacent"
    shared = sorted(publisher.tags & (set(brief.categories) | set(brief.adjacent_categories)) & attributes)
    if shared:
        note = f"Shared attribute: {shared[0].replace('_', ' ')}"
        return Factor(name="category", score=scores["attribute"], note=note), "attribute"
    return Factor(name="category", score=0.0, note="No category overlap"), "none"


def _audience(brief: Brief, publisher: Publisher, tuning: Tuning) -> tuple[Factor, bool]:
    """Age overlap and gender share; also whether both are unknown."""
    unknown = tuning.publisher.unknown_factor
    bounds = age_bounds(brief, tuning)
    age = age_overlap(bounds, publisher.age_min, publisher.age_max, unknown)
    split = publisher.audience.gender_split
    known_gender = brief.gender_skew in ("female", "male")
    gender = split.get(brief.gender_skew, 0.0) if known_gender else unknown
    weights = tuning.publisher.audience_weights
    score = weights["age"] * age + weights["gender"] * gender
    top = "female" if split.get("female", 0) >= split.get("male", 0) else "male"
    note = (f"Skews {publisher.audience.age_skew}, {round(split.get(top, 0.0) * 100)}% "
            f"{'women' if top == 'female' else 'men'}")
    return Factor(name="audience", score=score, note=note), bounds is None and not known_gender


def _income(brief: Brief, publisher: Publisher, tuning: Tuning) -> tuple[Factor, bool]:
    """How close the publisher's audience income is to what the price tier needs."""
    target = tuning.publisher.income_targets.get(brief.price_tier)
    if target is None:
        return Factor(name="income", score=tuning.publisher.unknown_factor, note="Price tier unknown"), True
    score = max(0.0, 1 - abs(publisher.income_rank - target) / tuning.publisher.income_scale)
    note = f"Income tier {INCOME_NAMES[publisher.income_rank]} vs {brief.price_tier}"
    return Factor(name="income", score=score, note=note), False


def _aov(brief: Brief, publisher: Publisher, tuning: Tuning) -> tuple[Factor, bool]:
    """The price against the publisher's average order, on a log scale."""
    if brief.price_usd is None or brief.price_usd <= 0:
        return Factor(name="aov", score=tuning.publisher.unknown_factor, note="Price unknown"), True
    ratio = math.log2(brief.price_usd / publisher.avg_order_value_usd)
    # a product cheaper than the typical basket can sit inside it; one far above it is the real mismatch
    scale = tuning.publisher.aov_log2_scale if ratio >= 0 else tuning.publisher.aov_below_log2_scale
    note = f"AOV ${publisher.avg_order_value_usd:.0f} vs ${brief.price_usd:.0f} price"
    return Factor(name="aov", score=max(0.0, 1 - abs(ratio) / scale), note=note), False


def score_publishers(brief: Brief, catalog: Catalog, tuning: Tuning,
                     exclude: set[str] = frozenset()) -> list[PublisherScore]:
    """Every publisher, best fit first. Excluded ids keep their fit but are never recommended."""
    brief = scoped(brief, catalog, tuning)
    settings = tuning.publisher
    rows = []
    for publisher in catalog.publishers:
        category, level = _category(brief, publisher, catalog, tuning)
        audience, audience_unknown = _audience(brief, publisher, tuning)
        income, income_unknown = _income(brief, publisher, tuning)
        aov, aov_unknown = _aov(brief, publisher, tuning)
        factors = [category, audience, income, aov]
        fit = sum(settings.weights[factor.name] * factor.score for factor in factors)
        if level in ("attribute", "none"):
            fit *= settings.no_category_penalty
        if not aov_unknown:
            fit *= settings.aov_gate_floor + (1 - settings.aov_gate_floor) * aov.score
        rows.append((fit, publisher, factors, [False, audience_unknown, income_unknown, aov_unknown]))
    rows.sort(key=lambda row: (-row[0], row[1].id))
    scores, rank = [], 0
    for fit, publisher, factors, unknown in rows:
        if publisher.id in exclude:
            recommended, reason = False, EXCLUDED_REASON
        else:
            recommended = fit >= settings.cutoff and rank < settings.max_recommended
            # the reason is the strongest factor (recommended) or the weakest (not), ignoring unknowns
            known = [factor for factor, is_unknown in zip(factors, unknown) if not is_unknown] or factors[:1]
            reason = (max if recommended else min)(known, key=lambda factor: factor.score).note
            rank += 1
        scores.append(PublisherScore(publisher_id=publisher.id, name=publisher.name, fit=round(fit, 3),
                                     factors=factors, recommended=recommended, stretch=False, reason=reason))
    return scores


def pick_publishers(brief: Brief, catalog: Catalog, tuning: Tuning,
                    exclude: set[str] = frozenset()) -> tuple[list[PublisherScore], bool]:
    """Scores, and whether the fit is weak. A weak fit marks the closest related publishers (some
    category link) as recommended stretch picks; when none is related, nothing is picked."""
    scores = score_publishers(brief, catalog, tuning, exclude)
    if sum(score.recommended for score in scores) >= tuning.publisher.weak_fit_min_recommended:
        return scores, False
    picked, marked = 0, []
    for score in scores:
        related = any(factor.name == "category" and factor.score > 0 for factor in score.factors)
        pick = score.publisher_id not in exclude and picked < tuning.publisher.weak_fit_show and related
        picked += pick
        marked.append(score.model_copy(update={"recommended": pick, "stretch": pick}))
    return marked, True


# ---- personas ----

def _affinity(brief: Brief, persona: Persona, parents: dict[str, set[str]], tuning: Tuning) -> Factor:
    """The best category link (direct, family, sibling, adjacent), plus a bonus when the brief names
    this persona's shopping mode ("mostly bought as gifts" -> The Gifter)."""
    scores = tuning.persona.affinity_scores
    attributes = set(tuning.publisher.attribute_tags)
    affinities = set(persona.category_affinities) - attributes
    categories = set(brief.categories) - attributes
    direct = sorted(affinities & categories)
    family = sorted((a, c) for a in affinities for c in categories
                    if c in parents.get(a, ()) or a in parents.get(c, ()))
    sibling = sorted((a, c) for a in affinities for c in categories if parents.get(a, set()) & parents.get(c, set()))
    adjacent = sorted(affinities & set(brief.adjacent_categories))
    if direct:
        link = Factor(name="affinity", score=scores["direct"], note=f"Affinity: {direct[0]}")
    elif family:
        note = f"Affinity: {family[0][0]} (under {family[0][1]})"
        link = Factor(name="affinity", score=scores["family"], note=note)
    elif sibling:
        link = Factor(name="affinity", score=scores["sibling"], note=f"Related: {sibling[0][0]} ~ {sibling[0][1]}")
    elif adjacent:
        link = Factor(name="affinity", score=scores["adjacent"], note=f"Adjacent affinity: {adjacent[0]}")
    else:
        link = Factor(name="affinity", score=0.0, note="No affinity overlap")
    modes = sorted(set(tuning.persona.attribute_affinities.get(persona.id, []))
                   & (set(brief.categories) | set(brief.adjacent_categories)))
    if not modes:
        return link
    score = min(1.0, max(link.score, scores["family"]) + tuning.persona.mode_bonus)
    return Factor(name="affinity", score=score, note=f"Shops for: {modes[0]}")


def _price(brief: Brief, persona: Persona, tuning: Tuning) -> Factor:
    """How close the persona's price sensitivity is to the brief's price tier."""
    ideal = tuning.persona.price_ideal.get(brief.price_tier)
    if ideal is None:
        return Factor(name="price", score=tuning.publisher.unknown_factor, note="Price tier unknown")
    score = max(0.0, 1 - abs(ideal - persona.price_rank) / tuning.persona.price_scale)
    note = f"{persona.price_sensitivity.capitalize()} price sensitivity vs {brief.price_tier}"
    return Factor(name="price", score=score, note=note)


def _age(brief: Brief, persona: Persona, tuning: Tuning) -> Factor:
    """How much of the brief's age range the persona covers."""
    bounds = age_bounds(brief, tuning)
    score = age_overlap(bounds, persona.age_min, persona.age_max, tuning.publisher.unknown_factor)
    note = ("Brief ages unknown" if bounds is None
            else f"Ages {persona.age_min}–{persona.age_max} vs {bounds[0]}–{bounds[1]}")
    return Factor(name="age", score=score, note=note)


def _shops_there(persona: Persona, chosen: list[tuple[Publisher, float]], parents: dict[str, set[str]],
                 tuning: Tuning) -> Factor:
    """Does this persona shop on the publishers picked in step 1? Per publisher, weighted by its
    fit: 0.6 x category link (an affinity is its category or subcategory 1.0, sits under its
    category 0.7) + 0.4 x the share of the persona's ages in its audience."""
    if not chosen:
        return Factor(name="publishers", score=tuning.publisher.unknown_factor, note="No publishers picked yet")
    affinities = set(persona.category_affinities)
    total = sum(fit for _, fit in chosen) or 1.0
    score, shops = 0.0, []
    for publisher, fit in chosen:
        if affinities & {publisher.category, *publisher.subcategories}:
            link = 1.0
        elif any(publisher.category in parents.get(word, ()) for word in affinities):
            link = tuning.persona.affinity_scores["family"]
        else:
            link = 0.0
        ages = age_overlap((persona.age_min, persona.age_max), publisher.age_min, publisher.age_max,
                           tuning.publisher.unknown_factor)
        score += fit / total * (0.6 * link + 0.4 * ages)
        if link:
            shops.append(publisher.name)
    note = f"Shops at {', '.join(shops[:2])}" if shops else "Rarely shops these publishers"
    return Factor(name="publishers", score=round(score, 3), note=note)


def _persona_fit(brief: Brief, persona: Persona, chosen: list[tuple[Publisher, float]],
                 parents: dict[str, set[str]], tuning: Tuning) -> tuple[float, list[Factor]]:
    """The unclamped fit and its factors: 4 weighted factors, then any of 3 penalties."""
    settings = tuning.persona
    affinity, price, age = _affinity(brief, persona, parents, tuning), _price(brief, persona, tuning), _age(brief, persona, tuning)
    shops = _shops_there(persona, chosen, parents, tuning)
    factors = [affinity, price, age, shops]
    weights = settings.weights  # added left to right, as the numbers were tuned (sum() rounds differently)
    fit = (weights["affinity"] * affinity.score + weights["price"] * price.score + weights["age"] * age.score
           + weights["publishers"] * shops.score)
    if affinity.score <= 0 and settings.niche_penalty:
        categories = {c for word in persona.category_affinities for c in parents.get(word, set())}
        if len(categories) == 1:
            note = f"Only shops {next(iter(categories)).replace('_', ' ')}"
            factors.append(Factor(name="niche", score=-settings.niche_penalty, note=note))
            fit -= settings.niche_penalty
    if age.score <= 0 and age_bounds(brief, tuning) is not None and settings.age_mismatch_penalty:
        factors.append(Factor(name="age_mismatch", score=-settings.age_mismatch_penalty,
                              note="Outside the brief's ages"))
        fit -= settings.age_mismatch_penalty
    conflicts = sorted({c.lower() for c in brief.conflicts} & {d.lower() for d in persona.disinterested_in})
    if conflicts:
        factors.append(Factor(name="conflict", score=-settings.conflict_penalty, note=f"Conflicts: {conflicts[0]}"))
        fit -= settings.conflict_penalty
    return fit, factors


def score_personas(brief: Brief, catalog: Catalog, tuning: Tuning,
                   recommended: list[PublisherScore]) -> list[PersonaScore]:
    """Every persona, best fit first, scored against step 1's recommended publishers."""
    brief = scoped(brief, catalog, tuning)
    parents = term_parents(catalog, tuning)
    chosen = [(catalog.publisher_by_id[score.publisher_id], score.fit) for score in recommended]
    rows = []
    for persona in catalog.personas:
        fit, factors = _persona_fit(brief, persona, chosen, parents, tuning)
        rows.append((max(0.0, min(1.0, fit)), persona, factors))
    rows.sort(key=lambda row: (-row[0], row[1].id))
    return [PersonaScore(persona_id=persona.id, name=persona.name, fit=round(fit, 3), factors=factors,
                         stretch=False) for fit, persona, factors in rows]


def select_personas(scores: list[PersonaScore], tuning: Tuning) -> list[PersonaScore]:
    """Personas at or above the cut-off (up to max); if fewer than min, stretch picks fill up,
    those with some category affinity first (price and age alone don't make a plausible shopper)."""
    settings = tuning.persona
    chosen = [score.model_copy(update={"stretch": False})
              for score in scores if score.fit >= settings.cutoff][: settings.max]
    if len(chosen) < settings.min:
        rest = sorted((score for score in scores if score.fit < settings.cutoff),
                      key=lambda score: all(f.score <= 0 for f in score.factors if f.name == "affinity"))
        chosen += [score.model_copy(update={"stretch": True}) for score in rest[: settings.min - len(chosen)]]
    return chosen
