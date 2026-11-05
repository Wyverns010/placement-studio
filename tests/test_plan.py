import pytest
from pydantic import ValidationError

from app.match import score_personas, score_publishers, select_personas
from app.models.ads import Creative
from app.models.plan import CampaignConfig
from app.models.scores import PublisherScore
from app.plan import (
    allocate,
    build_config,
    choose_pacing,
    frequency_cap,
    publisher_prices,
    recommended_budget,
)
from tests.conftest import CAT, T, brief


def prices(scores):
    return publisher_prices([score.publisher_id for score in scores], CAT, T)


def prices_of(publisher):
    return publisher_prices([publisher.id], CAT, T)[publisher.id]


def build(brief, publishers, personas, creatives, monthly_usd, weak_fit):
    """build_config reads a weak fit from the publishers' stretch flags."""
    marked = [p.model_copy(update={"stretch": weak_fit}) for p in publishers]
    return build_config(brief, marked, personas, creatives, monthly_usd, CAT, T)


# ---- numbers ----

def ps(pid: str, fit: float) -> PublisherScore:
    return PublisherScore(publisher_id=pid, name=pid, fit=fit, factors=[], recommended=True,
                          stretch=False, reason="r")


def by_name(name: str) -> str:
    return next(p.id for p in CAT.publishers if p.name == name)


def test_shares_sum_to_one_and_respect_floor():
    pubs = [ps(by_name("Pawline"), 0.9), ps(by_name("Ruffco"), 0.8), ps(by_name("Tailcrate"), 0.02)]
    items, unalloc = allocate(pubs, 25000, prices(pubs), T)
    assert sum(i.share for i in items) == pytest.approx(1.0, abs=1e-6)
    assert all(i.share >= T.budget.min_share - 1e-9 for i in items)
    assert sum(i.budget_usd for i in items) + unalloc == pytest.approx(25000, abs=0.05)


def test_budget_exceeds_reach_reports_unallocated():
    pubs = [ps(by_name("Pawline"), 0.9), ps(by_name("Tailcrate"), 0.6)]
    items, unalloc = allocate(pubs, 5_000_000, prices(pubs), T)
    assert unalloc > 0
    for i in items:
        cap = prices_of(CAT.publisher_by_id[i.publisher_id])[1]
        assert i.budget_usd <= cap + 0.01


def test_allocation_independent_of_raw_text():
    pubs = [ps(by_name("Pawline"), 0.9), ps(by_name("Ruffco"), 0.5)]
    assert allocate(pubs, 25000, prices(pubs), T) == allocate([p.model_copy() for p in pubs], 25000, prices([p.model_copy() for p in pubs]), T)


def test_empty_list():
    assert allocate([], 25000, prices([]), T) == ([], 25000)


def test_single_publisher_gets_full_share():
    single = [ps(by_name("Pawline"), 0.7)]
    items, unalloc = allocate(single, 1000, prices(single), T)
    assert items[0].share == pytest.approx(1.0) and items[0].budget_usd == 1000 and unalloc == 0


def test_too_many_publishers_for_floor_falls_back_to_equal():
    pubs = [ps(p.id, 0.9 - 0.05 * i) for i, p in enumerate(CAT.publishers[:12])]
    items, _ = allocate(pubs, 1000, prices(pubs), T)
    assert sum(i.share for i in items) == pytest.approx(1.0, abs=1e-6)
    assert max(i.share for i in items) == pytest.approx(min(i.share for i in items), abs=0.002)  # whole dollars


def test_target_cpa_subscription():
    b = brief(price_usd=60, business_model="subscription")
    assert recommended_budget(b, [ps(by_name("Pawline"), 0.9)], prices([ps(by_name("Pawline"), 0.9)]), CAT, False, T).cpa == 42


def test_target_cpa_falls_back_to_weighted_aov():
    pub = CAT.publisher_by_id[by_name("Pawline")]
    got = recommended_budget(brief(), [ps(pub.id, 0.9)], prices([ps(pub.id, 0.9)]), CAT, False, T).cpa
    assert got == round(T.bid.cpa_fraction_of_order_value * pub.avg_order_value_usd)


# ---- recommended budget, frequency and pacing from economics (config/tuning.yaml) ----


PAW, RUFF, TAIL = by_name("Pawline"), by_name("Ruffco"), by_name("Tailcrate")


def test_conversion_goal_and_rounding_are_tunables():
    b = T.budget
    assert b.learning_conversions_per_week == 50 and b.weeks_per_month == 4
    assert b.learning_conversions_per_week * b.weeks_per_month == 200 and b.round_to_usd == 500


def test_cpm_and_reach_follow_the_publishers_audience():
    paw, ruff = CAT.publisher_by_id[PAW], CAT.publisher_by_id[RUFF]  # mid-high 4.8M, mid 62M impressions
    assert prices_of(paw)[1] == 4_800_000 * 0.25 / 1000 * 13 == 15600
    assert prices_of(ruff)[1] == 62_000_000 * 0.25 / 1000 * 10 == 155000


def test_recommended_is_cpa_times_monthly_conversions_per_publisher_rounded_up():
    # price $60 one-off -> CPA round(0.35 x 60) = $21 -> $21 x 200 = $4,200 per publisher
    rec = recommended_budget(brief(price_usd=60), [ps(PAW, 0.9), ps(RUFF, 0.8)], prices([ps(PAW, 0.9), ps(RUFF, 0.8)]), CAT, False, T)
    assert rec.cpa == 21 and rec.capped == []
    assert rec.full_usd == 8500 and rec.usd == 8500  # 8,400 rounds up: enough for the 200


def test_recommended_capped_at_each_publishers_reach():
    # CPA $3,500 -> $700,000 wanted per publisher; both can only absorb their reach
    rec = recommended_budget(brief(price_usd=10000), [ps(PAW, 0.9), ps(RUFF, 0.8)], prices([ps(PAW, 0.9), ps(RUFF, 0.8)]), CAT, False, T)
    assert rec.capped == [PAW, RUFF]
    assert rec.usd == 171000  # 170,600 rounded up


@pytest.mark.parametrize("price,n_pubs,want", [(1, 1, 500), (5, 1, 500), (10**7, 3, None)])
def test_recommended_clamped_to_budget_bounds(price, n_pubs, want):
    pubs = [ps(p.id, 0.5) for p in CAT.publishers[:n_pubs]]
    rec = recommended_budget(brief(price_usd=price), pubs, prices(pubs), CAT, False, T)
    assert T.budget.min_usd <= rec.usd <= T.budget.max_usd
    if want is not None:
        assert rec.usd == want


def test_weak_fit_recommends_a_20_percent_test():
    pubs = [ps(PAW, 0.3), ps(RUFF, 0.3), ps(TAIL, 0.3)]
    rec = recommended_budget(brief(price_usd=80), pubs, prices(pubs), CAT, True, T)  # $28 x 200 x 3 = 16,800
    assert rec.full_usd == 17000 and rec.usd == 3000  # 20% = 3,400, capped at the $3,000 test max
    small = recommended_budget(brief(price_usd=5), pubs[:2], prices(pubs[:2]), CAT, True, T)  # $2 x 400 = 800 -> 1,000 x 20%
    assert small.usd == T.budget.min_usd


def test_weak_fit_test_capped_and_rounded():
    assert T.budget.weak_fit_test_max_usd == 3000
    pubs = [ps(PAW, 0.3), ps(RUFF, 0.3), ps(TAIL, 0.3)]
    big = recommended_budget(brief(price_usd=1000), pubs, prices(pubs), CAT, True, T)  # full >> cap
    assert big.full_usd > 15000 and big.usd == 3000
    # the test share rounds to the nearest $500, never an odd figure
    t = T.model_copy(deep=True)
    t.budget.weak_fit_test_fraction = 0.1  # 0.1 x 17,000 = 1,700 -> 1,500
    odd = recommended_budget(brief(price_usd=80), pubs, prices(pubs), CAT, True, t)
    assert odd.usd % t.budget.round_to_usd == 0 and odd.usd == 1500


def test_round_to_usd_must_be_positive():
    import yaml
    from pydantic import ValidationError

    from app.models.tuning import Tuning
    raw = yaml.safe_load(open("config/tuning.yaml"))
    raw["budget"]["round_to_usd"] = 0
    with pytest.raises(ValidationError):
        Tuning(**raw)


@pytest.mark.parametrize("tier,want", [("value", (5, 7)), ("mid", (4, 7)), ("premium", (3, 14)),
                                       ("luxury", (2, 21)), ("unknown", (3, 7))])
def test_frequency_by_price_tier(tier, want):
    assert frequency_cap(brief(price_tier=tier), False, T) == want


def test_frequency_subscription_adds_one_and_weak_fit_takes_one_off():
    assert frequency_cap(brief(price_tier="mid", business_model="subscription"), False, T) == (5, 7)
    assert frequency_cap(brief(price_tier="mid"), True, T) == (3, 7)
    assert frequency_cap(brief(price_tier="luxury"), True, T) == (1, 14)


def test_weak_fit_frequency_window_capped_for_a_short_test():
    assert T.frequency.weak_fit_max_per_days == 14
    assert frequency_cap(brief(price_tier="premium"), True, T) == (2, 14)
    assert frequency_cap(brief(price_tier="value"), True, T) == (4, 7)  # shorter windows unchanged
    assert frequency_cap(brief(price_tier="luxury"), False, T) == (2, 21)


def test_frequency_never_below_one():
    t = T.model_copy(deep=True)
    t.frequency.weak_fit_reduction = 5
    assert frequency_cap(brief(price_tier="luxury"), True, t)[0] == 1


@pytest.mark.parametrize("tier,weak,monthly,rec,want", [
    ("mid", True, 500, 500, "front_loaded"),
    ("luxury", True, 500, 500, "front_loaded"),
    ("luxury", False, 1000, 5000, "even"),
    ("premium", False, 1000, 5000, "even"),
    ("value", False, 1000, 5000, "accelerated"),
    ("mid", False, 1000, 5000, "accelerated"),
    ("mid", False, 5000, 5000, "even"),
    ("value", False, 9000, 5000, "even"),
    ("unknown", False, 1000, 5000, "even"),
])
def test_pacing_rules(tier, weak, monthly, rec, want):
    assert choose_pacing(brief(price_tier=tier), weak, monthly, rec) == want


def test_projection_is_plain_arithmetic_on_the_line_items():
    cfg, _, _ = _build(monthly=10_000)
    budget, cpa = cfg.budget, cfg.bid_strategy["target_usd"]
    assert budget.est_impressions == sum(li.est_impressions for li in cfg.line_items)
    assert budget.est_conversions == int(10_000 / cpa)
    assert budget.conversions_per_1k == round(budget.est_conversions / budget.est_impressions * 1000, 2)
    assert budget.est_roas == round(budget.est_revenue_usd / 10_000, 2)


def test_line_items_are_whole_dollars_and_the_shown_arithmetic_adds_up():
    pubs = [ps(PAW, 0.9), ps(RUFF, 0.8), ps(TAIL, 0.7)]
    items, unalloc = allocate(pubs, 19_500, prices(pubs), T)
    assert all(li.budget_usd == int(li.budget_usd) for li in items)
    assert sum(li.budget_usd for li in items) + unalloc == 19_500
    for li in items:  # budget / CPM x 1,000, by hand
        assert li.est_impressions == round(li.budget_usd / li.cpm_usd * 1000)


# ---- config ----

B = brief(product="Senior dog food", categories=["pet_food"], adjacent_categories=["pet_health", "subscription"],
          price_usd=60, price_tier="premium", business_model="subscription")


def _inputs(b=B):
    pubs = [p for p in score_publishers(b, CAT, T) if p.recommended]
    personas = select_personas(score_personas(b, CAT, T, []), T)
    creatives = [Creative(persona_id=p.persona_id, publisher_id=pubs[i % len(pubs)].publisher_id,
                          headline="h", body="b", cta="c", why="w") for i, p in enumerate(personas)]
    return pubs, personas, creatives


def _build(weak_fit=False, monthly=25000, b=B):
    pubs, personas, creatives = _inputs(b)
    return build(brief=b, publishers=pubs, personas=personas, creatives=creatives,
                        monthly_usd=monthly, weak_fit=weak_fit), pubs, personas


def test_config_validates_and_has_rationales():
    cfg, _, _ = _build()
    CampaignConfig.model_validate(cfg.model_dump())
    assert set(cfg.rationales) >= {"objective", "bid_strategy", "budget", "targeting", "frequency_cap", "guardrails"}
    assert "$42" in cfg.rationales["bid_strategy"] and "$25,000" in cfg.rationales["budget"]


def test_weak_fit_recommends_test_budget_and_user_override_wins():
    cfg, pubs, _ = _build(weak_fit=True, monthly=None)
    rec = recommended_budget(B, pubs, prices(pubs), CAT, True, T)
    assert cfg.budget.test_budget is True and cfg.budget.source == "recommended"
    assert cfg.budget.monthly_usd == cfg.budget.recommended_usd == rec.usd
    assert "20%" in cfg.rationales["budget"] and "weak" in cfg.rationales["budget"]
    user, _, _ = _build(weak_fit=True, monthly=25000)
    assert user.budget.monthly_usd == 25000 and user.budget.source == "user"
    assert user.budget.test_budget is False and user.budget.recommended_usd == rec.usd
    assert (f"You chose $25,000; we'd suggest a ${rec.usd:,.0f} test because nothing in the catalog "
            "is a strong match") in user.rationales["budget"]


def test_normal_budget_not_test():
    cfg, _, _ = _build()
    assert cfg.budget.test_budget is False and cfg.budget.pacing == "even"


def test_fields_and_creatives():
    cfg, pubs, personas = _build()
    assert cfg.conversion_event == "subscription_start" and cfg.bid_strategy["target_usd"] == 42
    assert cfg.targeting["geo"] == ["US"] and cfg.targeting["personas"] == [p.persona_id for p in personas]
    assert cfg.targeting["interests"] == ["pet_food", "pet_health", "subscription"]
    assert cfg.targeting["gender"] == "all"
    assert all(li.ads for li in cfg.line_items)
    assert cfg.guardrails["min_impressions"] == 2000
    assert cfg.campaign_id == _build()[0].campaign_id and cfg.campaign_id.startswith("cmp_senior-dog-food_")


def test_age_range_from_brief_or_personas():
    cfg, _, personas = _build(b=brief(**{**B.model_dump(), "age_min": 30, "age_max": 50}))
    assert cfg.targeting["age_range"] == [30, 50]
    cfg2, _, personas = _build()
    ranges = [(x.age_min, x.age_max) for x in CAT.personas if x.id in {p.persona_id for p in personas}]
    assert cfg2.targeting["age_range"] == [min(r[0] for r in ranges), max(r[1] for r in ranges)]


def test_one_sided_age_fills_bounds_in_config():
    b = B.model_copy(update={"age_min": 50, "age_max": None})
    cfg, _, _ = _build(b=b)
    assert cfg.targeting["age_range"] == [50, T.input.age_ceiling]
    assert "None" not in cfg.rationales["targeting"]
    assert f"ages 50-{T.input.age_ceiling}" in cfg.rationales["targeting"]
    b = B.model_copy(update={"age_min": None, "age_max": 35})
    cfg, _, _ = _build(b=b)
    assert cfg.targeting["age_range"] == [T.input.age_floor, 35]


def test_budget_defaults_to_recommended_with_source():
    cfg, pubs, _ = _build(monthly=None)
    rec = recommended_budget(B, pubs, prices(pubs), CAT, False, T)
    assert cfg.budget.monthly_usd == cfg.budget.recommended_usd == rec.usd
    assert cfg.budget.source == "recommended"
    r = cfg.rationales["budget"]
    # the inputs: target CPA, the monthly conversion goal and why, publisher count, rounding unit
    assert f"${rec.cpa:,.0f} target CPA" in r and "200 conversions" in r and "50 a week" in r
    assert f"{len(pubs)} publishers" in r and "$500" in r
    p = cfg.rationales["projection"]
    assert "impressions" in p and "ROAS" in p and "per 1,000 impressions" in p


def test_user_budget_wins_and_rationale_names_both():
    cfg, pubs, _ = _build(monthly=25000)
    rec = recommended_budget(B, pubs, prices(pubs), CAT, False, T)
    assert cfg.budget.monthly_usd == 25000 and cfg.budget.source == "user"
    assert cfg.budget.recommended_usd == rec.usd
    assert "$25,000" in cfg.rationales["budget"] and f"${rec.usd:,.0f}" in cfg.rationales["budget"]


def test_frequency_and_pacing_in_config_with_rationales():
    cfg, _, _ = _build()  # premium subscription: 3/14 + 1
    assert cfg.frequency_cap == {"impressions": 4, "per_days": 14}
    f = cfg.rationales["frequency_cap"]
    assert "premium" in f and "subscription" in f and "4" in f and "14" in f
    weak, _, _ = _build(weak_fit=True)
    assert weak.frequency_cap == {"impressions": 3, "per_days": 14}
    assert "test" in weak.rationales["frequency_cap"]
    assert cfg.budget.pacing == "even" and "premium" in cfg.rationales["pacing"]
    assert weak.budget.pacing == "front_loaded" and "test" in weak.rationales["pacing"]


def test_pacing_accelerated_for_mid_tier_below_recommendation():
    b = B.model_copy(update={"price_tier": "mid", "business_model": "one_off"})
    cfg, pubs, _ = _build(b=b, monthly=500)
    assert recommended_budget(b, pubs, prices(pubs), CAT, False, T).usd > 500
    assert cfg.budget.pacing == "accelerated" and "below" in cfg.rationales["pacing"]


def test_weak_fit_rationale_names_the_minimum_floor():
    b = B.model_copy(update={"price_usd": 8, "business_model": "one_off"})
    cfg, pubs, _ = _build(weak_fit=True, monthly=None, b=b)
    rec = recommended_budget(b, pubs, prices(pubs), CAT, True, T)
    assert rec.full_usd * T.budget.weak_fit_test_fraction < T.budget.min_usd == rec.usd
    assert "raised to the $500 minimum" in cfg.rationales["budget"]
    plain, _, _ = _build(weak_fit=True, monthly=None)
    assert "minimum" not in plain.rationales["budget"]


def test_every_creative_is_in_rotation_on_its_own_publisher():
    pubs, personas, _ = _inputs()
    # more personas than publishers: two ads written for the first publisher
    creatives = [Creative(persona_id=p.persona_id,
                          publisher_id=pubs[min(i, 1) % len(pubs)].publisher_id,
                          headline="h", body="b", cta="c", why="w") for i, p in enumerate(personas)]
    cfg = build(brief=B, publishers=pubs, personas=personas, creatives=creatives,
                       monthly_usd=None, weak_fit=False)
    placed = {a for li in cfg.line_items for a in li.ads}
    assert placed == {c.persona_id for c in creatives}
    for li in cfg.line_items:
        own = [c.persona_id for c in creatives if c.publisher_id == li.publisher_id]
        if own:
            assert li.ads == own
    assert "rotate" in cfg.rationales["line_items"]
    single, _, _ = _build()
    assert all(len(li.ads) == 1 for li in single.line_items)
    assert "rotate" not in single.rationales["line_items"]


def test_guardrail_limit_is_one_rounded_value():
    b = B.model_copy(update={"price_usd": 60, "business_model": "one_off"})  # CPA $21 x 1.5 = 31.5
    cfg, _, _ = _build(b=b)
    assert cfg.guardrails["cpa_limit_usd"] == 32
    assert "exceeds $32 " in cfg.rationales["guardrails"]


def test_weak_fit_rationale_states_the_test_cap():
    b = B.model_copy(update={"price_usd": 1000, "business_model": "one_off"})
    pubs, personas, creatives = _inputs()
    cfg = build(brief=b, publishers=pubs, personas=personas, creatives=creatives,
                       monthly_usd=None, weak_fit=True)
    rec = recommended_budget(b, pubs, prices(pubs), CAT, True, T)
    assert rec.usd == T.budget.weak_fit_test_max_usd == 3000
    assert cfg.budget.monthly_usd == 3000
    r = cfg.rationales["budget"]
    assert "capped at $3,000" in r and "20%" in r
    lux = build(brief=b.model_copy(update={"price_tier": "luxury"}), publishers=pubs,
                       personas=personas, creatives=creatives, monthly_usd=None, weak_fit=True)
    assert lux.frequency_cap == {"impressions": 1, "per_days": 14}
    assert "shortened to 14 days" in lux.rationales["frequency_cap"]
    assert lux.rationales["frequency_cap"].startswith("At most 1 impression per person")


def test_targeting_rationale_never_prints_none_ages():
    cfg = build(brief=B, publishers=_inputs()[0], personas=[], creatives=[],
                       monthly_usd=None, weak_fit=False)
    assert cfg.targeting["age_range"] == [None, None]
    assert "None" not in cfg.rationales["targeting"]
    assert "all ages" in cfg.rationales["targeting"]


def test_line_items_rationale_names_reused_ads():
    pubs, personas, _ = _inputs()
    assert len(pubs) >= 2
    # one ad only, written for the first publisher: the others reuse it
    c = Creative(persona_id=personas[0].persona_id,
                 publisher_id=pubs[0].publisher_id, headline="h", body="b", cta="c", why="w")
    cfg = build(brief=B, publishers=pubs, personas=personas, creatives=[c],
                       monthly_usd=None, weak_fit=False)
    r = cfg.rationales["line_items"]
    name = personas[0].name.removeprefix("The ")
    assert f"{pubs[1].name} reuses the {name} ad written for {pubs[0].name}" in r
    assert "the The" not in r


def test_budget_is_typed_and_json_shape_is_stable():
    cfg, _, _ = _build()
    assert set(cfg.model_dump(mode="json")["budget"]) == {
        "monthly_usd", "recommended_usd", "source", "pacing", "unallocated_usd", "test_budget",
        "est_impressions", "est_conversions", "est_revenue_usd", "est_roas", "conversions_per_1k", "cpa_is_stretch"}
    bad = cfg.model_dump()
    bad["budget"]["pacing"] = "sideways"
    with pytest.raises(ValidationError):
        CampaignConfig.model_validate(bad)
