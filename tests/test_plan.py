import pytest
from pydantic import ValidationError

from app.match import score_personas, score_publishers, select_personas
from app.models.ads import Creative
from app.models.plan import CampaignConfig
from app.models.scores import PublisherScore
from app.plan import build_config, order_value, recommended_budget, split
from tests.conftest import CAT, T, brief


def ps(pid: str, fit: float) -> PublisherScore:
    return PublisherScore(publisher_id=pid, name=pid, fit=fit, factors=[], recommended=True, stretch=False, reason="r")


def by_name(name: str) -> str:
    return next(p.id for p in CAT.publishers if p.name == name)


PAW, RUFF, TAIL = by_name("Pawline"), by_name("Ruffco"), by_name("Tailcrate")


# ---- numbers ----

def test_order_value_is_the_price_or_fit_weighted_aov():
    assert order_value(brief(price_usd=60), [ps(PAW, 0.9)], CAT) == 60
    paw, ruff = CAT.publisher_by_id[PAW].avg_order_value_usd, CAT.publisher_by_id[RUFF].avg_order_value_usd
    got = order_value(brief(), [ps(PAW, 0.75), ps(RUFF, 0.25)], CAT)
    assert got == pytest.approx(0.75 * paw + 0.25 * ruff)


def test_recommended_budget_is_conversions_times_cpa_rounded_up_and_bounded():
    assert recommended_budget(21, 2, T) == 8500  # 200 x $21 x 2 = 8,400 -> up to 8,500
    assert recommended_budget(1, 1, T) == T.budget.min_usd
    assert recommended_budget(10**7, 3, T) == T.budget.max_usd


def test_split_is_whole_dollars_by_fit_and_adds_up_exactly():
    items = split([ps(PAW, 0.9), ps(RUFF, 0.8), ps(TAIL, 0.7)], 10_000, CAT, T)
    assert all(li.budget_usd == int(li.budget_usd) for li in items)
    assert sum(li.budget_usd for li in items) == 10_000
    assert sum(li.share for li in items) == pytest.approx(1.0)
    assert [li.budget_usd for li in items] == sorted((li.budget_usd for li in items), reverse=True)
    for li in items:  # CPM by audience income; impressions = budget / CPM x 1,000
        income = CAT.publisher_by_id[li.publisher_id].audience.income_tier
        assert li.cpm_usd == T.budget.cpm_by_income_usd.get(income, T.budget.assumed_cpm_usd)
        assert li.est_impressions == round(li.budget_usd / li.cpm_usd * 1000)


def test_split_rounding_remainder_goes_to_the_best_fit():
    items = split([ps(PAW, 1), ps(RUFF, 1), ps(TAIL, 1)], 1000, CAT, T)  # 333.33 each
    assert [li.budget_usd for li in items] == [334, 333, 333]


def test_split_edge_cases():
    assert split([], 1000, CAT, T) == []
    zero = split([ps(PAW, 0), ps(RUFF, 0)], 1000, CAT, T)
    assert [li.budget_usd for li in zero] == [500, 500]


# ---- config ----

B = brief(product="Senior dog food", categories=["pet_food"], adjacent_categories=["pet_health", "subscription"],
          price_usd=60, price_tier="premium", business_model="subscription")


def _inputs(b=B):
    pubs = [p for p in score_publishers(b, CAT, T) if p.recommended]
    personas = select_personas(score_personas(b, CAT, T, []), T)
    creatives = [Creative(persona_id=p.persona_id, publisher_id=pubs[i % len(pubs)].publisher_id,
                          headline="h", body="b", cta="c", why="w") for i, p in enumerate(personas)]
    return pubs, personas, creatives


def _build(monthly=None, b=B, **kw):
    pubs, personas, creatives = _inputs(b)
    return build_config(b, pubs, personas, creatives, monthly, CAT, T, **kw), pubs, personas


def test_config_fields():
    cfg, _, personas = _build()
    CampaignConfig.model_validate(cfg.model_dump())
    assert cfg.conversion_event == "subscription_start"
    assert cfg.bid_strategy == {"type": "target_cpa", "target_usd": 21}  # 35% of $60
    assert cfg.targeting["geo"] == ["US"] and cfg.targeting["gender"] == "all"
    assert cfg.targeting["personas"] == [p.persona_id for p in personas]
    assert cfg.targeting["interests"] == ["pet_food", "pet_health", "subscription"]
    assert cfg.frequency_cap == {"impressions": 3, "per_days": 14}  # premium tier
    assert cfg.guardrails == {"pause_if_cpa_over_x": 1.5, "cpa_limit_usd": 32.0, "min_impressions": 2000}
    assert cfg.campaign_id == _build()[0].campaign_id and cfg.campaign_id.startswith("cmp_senior-dog-food_")
    assert set(cfg.rationales) == {"objective", "bid_strategy", "budget", "projection", "targeting",
                                   "frequency_cap", "pacing", "guardrails", "line_items"}


def test_budget_recommended_by_default_and_user_wins():
    cfg, pubs, _ = _build()
    assert cfg.budget.monthly_usd == cfg.budget.recommended_usd == recommended_budget(21, len(pubs), T)
    assert cfg.budget.source == "recommended" and "200 conversions" in cfg.rationales["budget"]
    user, _, _ = _build(monthly=25_000)
    assert user.budget.monthly_usd == 25_000 and user.budget.source == "user"
    assert user.budget.recommended_usd == cfg.budget.recommended_usd
    assert "You set $25,000" in user.rationales["budget"]


def test_projection_is_plain_arithmetic_on_the_line_items():
    cfg, _, _ = _build(monthly=10_000)
    budget = cfg.budget
    assert budget.est_impressions == sum(li.est_impressions for li in cfg.line_items)
    assert budget.est_conversions == int(10_000 / 21)
    assert budget.est_revenue_usd == budget.est_conversions * 60
    assert budget.est_roas == round(budget.est_revenue_usd / 10_000, 2)
    assert "ROAS" in cfg.rationales["projection"]


def test_pacing_is_even_unless_given():
    assert _build()[0].budget.pacing == "even"
    cfg, _, _ = _build(pacing="front_loaded")
    assert cfg.budget.pacing == "front_loaded" and "note" in cfg.rationales["pacing"]


def test_age_range_from_brief_then_personas_then_none():
    assert _build(b=B.model_copy(update={"age_min": 30, "age_max": 50}))[0].targeting["age_range"] == [30, 50]
    assert _build(b=B.model_copy(update={"age_min": 50}))[0].targeting["age_range"] == [50, T.input.age_ceiling]
    cfg, _, personas = _build()
    chosen = [CAT.persona_by_id[p.persona_id] for p in personas]
    assert cfg.targeting["age_range"] == [min(p.age_min for p in chosen), max(p.age_max for p in chosen)]
    bare = build_config(B, _inputs()[0], [], [], None, CAT, T)
    assert bare.targeting["age_range"] == [None, None] and "all ages" in bare.rationales["targeting"]


def test_each_line_item_runs_its_own_ads_or_the_best_personas():
    pubs, personas, _ = _inputs()
    own = Creative(persona_id=personas[1].persona_id, publisher_id=pubs[0].publisher_id,
                   headline="h", body="b", cta="c", why="w")
    cfg = build_config(B, pubs, personas, [own], None, CAT, T)
    assert all(li.ads == [own.persona_id] for li in cfg.line_items)  # first: written for it; rest: reuse it
    placed = {a for li in _build()[0].line_items for a in li.ads}
    assert placed == {c.persona_id for c in _inputs()[2]}


def test_excluded_publishers_get_no_line_item():
    pubs, personas, creatives = _inputs()
    cfg = build_config(B, pubs, personas, creatives, None, CAT, T, exclude={pubs[0].publisher_id})
    assert pubs[0].publisher_id not in {li.publisher_id for li in cfg.line_items}


def test_budget_json_shape_and_pacing_is_validated():
    cfg, _, _ = _build()
    assert set(cfg.model_dump(mode="json")["budget"]) == {
        "monthly_usd", "recommended_usd", "source", "pacing",
        "est_impressions", "est_conversions", "est_revenue_usd", "est_roas"}
    bad = cfg.model_dump()
    bad["budget"]["pacing"] = "sideways"
    with pytest.raises(ValidationError):
        CampaignConfig.model_validate(bad)
