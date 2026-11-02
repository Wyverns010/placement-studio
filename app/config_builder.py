from __future__ import annotations

import hashlib
import math
import re

from app.budget import (Pacing, allocate, cpm_usd, frequency_cap, order_value_used, pacing,
                        projection, recommended_budget)
from app.catalog import Catalog
from app.match import age_bounds
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
        own = [c.creative_id for c in ordered if c.publisher_id == li.publisher_id]
        out.append(li.model_copy(update={"creative_id": own[0] if own else fallback.creative_id,
                                         "extra_creative_ids": own[1:]}))
    return out


def build_config(*, brief: Brief, gate: GateResult, publishers: list[PublisherScore],
                 personas: list[PersonaScore], creatives: list[Creative],
                 monthly_usd: float | None, weak_fit: bool, catalog: Catalog,
                 t: Tuning, pacing_override: Pacing | None = None) -> CampaignConfig:
    """`monthly_usd` None means use the recommended budget; a user's figure always wins, as does
    a pacing the user asked for (`pacing_override`, from the media planner's validated tool)."""
    rec = recommended_budget(brief, publishers, catalog, weak_fit, t)
    source = "recommended" if monthly_usd is None else "user"
    monthly_usd = rec.usd if monthly_usd is None else monthly_usd
    items, unallocated = allocate(publishers, catalog, monthly_usd, t)
    items = _assign_creatives(items, personas, creatives)
    cpa = rec.cpa
    subscription = brief.business_model == "subscription"
    bid = t.bid
    freq_n, freq_days = frequency_cap(brief, weak_fit, t)
    code_pace = pacing(brief, weak_fit, monthly_usd, rec.usd)
    pace = pacing_override or code_pace
    order_value = order_value_used(brief, publishers, catalog)
    order_value_ltv = order_value * (bid.subscription_ltv_multiplier if subscription else 1)
    proj = projection(items, cpa, order_value_ltv, t)

    bounds = age_bounds(brief, t)
    if bounds is not None:
        age_range = list(bounds)
    elif personas:
        ages = [(p.age_min, p.age_max) for p in catalog.personas
                if p.id in {s.persona_id for s in personas}]
        age_range = [min(a for a, _ in ages), max(b for _, b in ages)] if ages else [None, None]
    else:
        age_range = [None, None]
    gender = brief.gender_skew if brief.gender_skew in ("female", "male") else "all"
    interests = list(dict.fromkeys(brief.categories + brief.adjacent_categories))  # dedup, keep order
    cpa_limit = float(math.floor(cpa * bid.guardrail_cpa_multiple + 0.5))  # whole dollars, half up

    ltv = f" × {bid.subscription_ltv_multiplier:.1f} subscription LTV" if subscription else ""
    src = "your price" if brief.price_usd else "fit-weighted publisher AOV"
    rationales = {
        "objective": "Conversions: the goal is "
                     + ("subscription starts" if subscription else "purchases"),
        "bid_strategy": f"{bid.cpa_fraction_of_order_value:.0%} of ${order_value:,.0f} order value ({src})"
                        f"{ltv} = ${cpa:,.0f} target CPA",
        "budget": _budget_rationale(rec, source, monthly_usd, unallocated, weak_fit, publishers,
                                    catalog, t),
        "projection": _projection_rationale(proj, cpa, order_value_ltv, monthly_usd, items,
                                            {p.publisher_id: p.name for p in publishers}, subscription, t),
        "targeting": f"{len(personas)} personas, interests {', '.join(interests) or 'none'}, "
                     f"{_ages_text(age_range)}, gender {gender}, US",
        "frequency_cap": _frequency_rationale(brief, weak_fit, freq_n, freq_days, t),
        "pacing": _pacing_rationale(brief, weak_fit, code_pace, monthly_usd, rec.usd)
                  if pace == code_pace else
                  f"{_PACE_WORD[pace]}: you asked for it (we'd pick {_PACE_WORD[code_pace].lower()}: "
                  f"{_pacing_rationale(brief, weak_fit, code_pace, monthly_usd, rec.usd).split(': ', 1)[1]})",
        "guardrails": f"Pause if CPA exceeds ${cpa_limit:,.0f} ({bid.guardrail_cpa_multiple:g}× target) "
                      f"after {bid.guardrail_min_impressions:,} impressions",
        "line_items": f"{len(items)} publishers, budget share proportional to fit with a "
                      f"{t.budget.min_share:.0%} floor" + _rotation_note(items, publishers)
                      + _reuse_note(items, publishers, personas, creatives),
    }
    return CampaignConfig(
        campaign_id=_campaign_id(brief, publishers, personas, monthly_usd),
        objective="conversions",
        conversion_event="subscription_start" if subscription else "purchase",
        budget={"monthly_usd": round(monthly_usd, 2), "recommended_usd": rec.usd, "source": source,
                "pacing": pace, "unallocated_usd": unallocated, "test_budget": weak_fit and source == "recommended",
                "conversions_goal": t.budget.conversions_per_month,
                "est_impressions": proj.impressions, "est_conversions": proj.conversions,
                "est_revenue_usd": proj.revenue_usd, "est_roas": proj.roas,
                "conversions_per_1k": proj.conversions_per_1k, "cpa_is_stretch": proj.stretch},
        bid_strategy={"type": "target_cpa", "target_usd": cpa},
        targeting={"age_range": age_range, "gender": gender, "geo": GEO,
                   "interests": interests, "personas": [p.persona_id for p in personas]},
        line_items=items,
        frequency_cap={"impressions": freq_n, "per_days": freq_days},
        guardrails={"pause_if_cpa_over_x": bid.guardrail_cpa_multiple, "cpa_limit_usd": cpa_limit,
                    "min_impressions": bid.guardrail_min_impressions},
        rationales=rationales,
        decision_trace={"gate_impl": gate.impl, "gate_confidence": gate.confidence,
                        "gate_threshold": gate.threshold,
                        "publisher_fits": {p.publisher_id: p.fit for p in publishers},
                        "persona_fits": {p.persona_id: p.fit for p in personas},
                        "weak_fit": weak_fit},
    )


_PACE_WORD = {"front_loaded": "Front-loaded", "even": "Even", "accelerated": "Accelerated"}


def _ages_text(age_range: list) -> str:
    lo, hi = age_range
    if lo is None and hi is None:
        return "all ages"
    if lo is None:
        return f"ages up to {hi}"
    if hi is None:
        return f"ages {lo}+"
    return f"ages {lo}-{hi}"


def _reuse_note(items: list[LineItem], publishers: list[PublisherScore],
                personas: list[PersonaScore], creatives: list[Creative]) -> str:
    """Line items with no ad of their own serve one written for another publisher: say so."""
    pub_names = {p.publisher_id: p.name for p in publishers}
    persona_names = {p.persona_id: p.name for p in personas}
    by_id = {c.creative_id: c for c in creatives}
    notes = []
    for li in items:
        c = by_id.get(li.creative_id or "")
        if c and c.publisher_id != li.publisher_id:
            persona = re.sub(r"^the\s+", "", persona_names.get(c.persona_id, c.persona_id),
                             flags=re.IGNORECASE)
            notes.append(f"{pub_names.get(li.publisher_id, li.publisher_id)} reuses the "
                         f"{persona} ad written for "
                         f"{pub_names.get(c.publisher_id, c.publisher_id)}")
    return "; " + ", ".join(notes) if notes else ""


def _rotation_note(items: list[LineItem], publishers: list[PublisherScore]) -> str:
    names = {p.publisher_id: p.name for p in publishers}
    rot = [f"{1 + len(li.extra_creative_ids)} ads rotate on {names.get(li.publisher_id, li.publisher_id)}"
           for li in items if li.extra_creative_ids]
    return "; " + ", ".join(rot) + " (each written for that publisher)" if rot else ""


def _budget_rationale(rec, source: str, monthly_usd: float, unallocated: float, weak_fit: bool,
                      publishers: list[PublisherScore], catalog: Catalog, t: Tuning) -> str:
    b = t.budget
    n = len(publishers)
    goal = b.conversions_per_month
    names = {p.publisher_id: p.name for p in publishers}
    why = (f"Recommended ${rec.usd:,.0f}/mo. Goal: {goal} conversions per publisher a month "
           f"({b.learning_conversions_per_week} a week, what a CPA bid needs to leave learning) × "
           f"${rec.cpa:,.0f} target CPA = ${rec.cpa * goal:,.0f} each, across {n} "
           f"publisher{'' if n == 1 else 's'}")
    for pid in rec.capped:
        pub = catalog.publisher(pid)
        cap = pub.monthly_impressions * b.max_share_of_impressions / 1000 * cpm_usd(pub, t)
        why += (f"; {names.get(pid, pid)} capped at its reach ({b.max_share_of_impressions:.0%} of "
                f"{pub.monthly_impressions / 1e6:g}M impressions at ${cpm_usd(pub, t):g} CPM = ${cap:,.0f})")
    why += f". Rounded up to ${b.round_to_usd:,.0f}, within ${b.min_usd:,.0f}–${b.max_usd:,.0f}"
    if weak_fit:
        share = rec.full_usd * b.weak_fit_test_fraction
        why += (f", then a test because fit is weak: {b.weak_fit_test_fraction:.0%} of "
                f"${rec.full_usd:,.0f}, capped at ${b.weak_fit_test_max_usd:,.0f}, "
                f"rounded to ${b.round_to_usd:,.0f}")
        if min(share, b.weak_fit_test_max_usd) < b.min_usd:
            why += f" (raised to the ${b.min_usd:,.0f} minimum)"
    if source == "user" and weak_fit:
        why += (f". You chose ${monthly_usd:,.0f}; we'd suggest a ${rec.usd:,.0f} test because nothing "
                "in the catalog is a strong match")
    elif source == "user":
        why += f". You set ${monthly_usd:,.0f}/mo, which is used instead"
    why += (". Split by fit; each publisher's CPM follows its audience's income "
            f"({', '.join(f'{k} ${v:g}' for k, v in b.cpm_by_income_usd.items())})")
    if unallocated:
        why += f"; ${unallocated:,.0f} unallocated (beyond publisher reach)"
    return why


def _projection_rationale(p, cpa: float, value: float, spend: float, items: list[LineItem],
                          names: dict[str, str], subscription: bool, t: Tuning) -> str:
    """The projection with its arithmetic shown, using the first line item as the worked example."""
    if not items:
        return "No line items, so nothing to project"
    li = items[0]
    kind = "subscription value (order value × LTV)" if subscription else "order value"
    why = (f"Impressions: each publisher's budget ÷ its CPM × 1,000, added up "
           f"({names.get(li.publisher_id, li.publisher_id)}: ${li.budget_usd:,.0f} ÷ ${li.cpm_usd:g} × 1,000 "
           f"= {li.est_impressions:,}) = {p.impressions:,}. "
           f"Conversions: ${spend:,.0f} ÷ ${cpa:,.0f} target CPA = {p.conversions:,}. "
           f"Revenue: {p.conversions:,} × ${value:,.0f} {kind} = ${p.revenue_usd:,.0f}. "
           f"ROAS: ${p.revenue_usd:,.0f} ÷ ${spend:,.0f} = {p.roas:g}× (about 1 ÷ "
           f"{t.bid.cpa_fraction_of_order_value:.0%}, because the CPA is {t.bid.cpa_fraction_of_order_value:.0%} "
           "of that value). "
           f"Check: {p.conversions:,} ÷ {p.impressions:,} impressions = {p.conversions_per_1k:g} conversions "
           "per 1,000 impressions")
    cap = t.budget.max_conversions_per_1k_impressions
    if p.stretch:
        why += f", above the ~{cap:g} per 1,000 checkout offers usually reach: the CPA is optimistic"
    else:
        why += f", under the ~{cap:g} per 1,000 checkout offers usually reach, so the CPA is realistic"
    return why


def _frequency_rationale(brief: Brief, weak_fit: bool, n: int, days: int, t: Tuning) -> str:
    f = t.frequency
    tier = brief.price_tier if brief.price_tier in f.by_price_tier else "unknown"
    base = f.by_price_tier[tier]
    parts = [f"{tier} price tier: {base.impressions} per {base.per_days} days"]
    if brief.business_model == "subscription":
        parts.append(f"+{f.subscription_extra} for a subscription")
    if weak_fit:
        parts.append(f"−{f.weak_fit_reduction} for a weak-fit test")
        if days < base.per_days:
            parts.append(f"window shortened to {days} days so the test learns fast")
    return (f"At most {n} impression{'' if n == 1 else 's'} per person every {days} days "
            f"({', '.join(parts)})")


def _pacing_rationale(brief: Brief, weak_fit: bool, pace: str, monthly_usd: float,
                      recommended_usd: float) -> str:
    if weak_fit:
        return "Front-loaded: a small weak-fit test should learn fast"
    if pace == "accelerated":
        return (f"Accelerated: a {brief.price_tier}-tier buy with ${monthly_usd:,.0f} below the "
                f"${recommended_usd:,.0f} recommendation, so spend it while it converts")
    if brief.price_tier in ("premium", "luxury"):
        return f"Even: a {brief.price_tier}-tier purchase is considered, so reminders are spread out"
    return f"Even: ${monthly_usd:,.0f} meets the ${recommended_usd:,.0f} recommendation" \
        if monthly_usd >= recommended_usd else f"Even: {brief.price_tier} price tier"
