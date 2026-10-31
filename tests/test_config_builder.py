from app.budget import recommended_budget
from app.config_builder import build_config
from app.match import score_personas, score_publishers, select_personas
from app.models import CampaignConfig, Creative, GateResult
from tests.conftest import CAT, T, brief

B = brief(product="Senior dog food", categories=["pet_food"], adjacent_categories=["pet_health", "subscription"],
          price_usd=60, price_tier="premium", business_model="subscription")
GATE = GateResult(outcome="proceed", confidence=0.9, threshold=0.7, impl="laya", signals={})


def _inputs(b=B):
    pubs = [p for p in score_publishers(b, CAT, T) if p.recommended]
    personas = select_personas(score_personas(b, CAT, T), T)
    creatives = [Creative(creative_id=f"c{i}", persona_id=p.persona_id, publisher_id=pubs[i % len(pubs)].publisher_id,
                          headline="h", body="b", cta="c", why="w") for i, p in enumerate(personas)]
    return pubs, personas, creatives


def _build(weak_fit=False, monthly=25000, b=B):
    pubs, personas, creatives = _inputs(b)
    return build_config(brief=b, gate=GATE, publishers=pubs, personas=personas, creatives=creatives,
                        monthly_usd=monthly, weak_fit=weak_fit, catalog=CAT, t=T), pubs, personas


def test_config_validates_and_has_rationales():
    cfg, _, _ = _build()
    CampaignConfig.model_validate(cfg.model_dump())
    assert set(cfg.rationales) >= {"objective", "bid_strategy", "budget", "targeting", "frequency_cap", "guardrails"}
    assert "$42" in cfg.rationales["bid_strategy"] and "$25,000" in cfg.rationales["budget"]


def test_weak_fit_recommends_test_budget_and_user_override_wins():
    cfg, pubs, _ = _build(weak_fit=True, monthly=None)
    rec = recommended_budget(B, pubs, CAT, True, T)
    assert cfg.budget["test_budget"] is True and cfg.budget["source"] == "recommended"
    assert cfg.budget["monthly_usd"] == cfg.budget["recommended_usd"] == rec.usd
    assert "20%" in cfg.rationales["budget"] and "weak" in cfg.rationales["budget"]
    user, _, _ = _build(weak_fit=True, monthly=25000)
    assert user.budget["monthly_usd"] == 25000 and user.budget["source"] == "user"
    assert user.budget["test_budget"] is False and user.budget["recommended_usd"] == rec.usd
    assert (f"You chose $25,000; we'd suggest a ${rec.usd:,.0f} test because nothing in the catalog "
            "is a strong match") in user.rationales["budget"]


def test_normal_budget_not_test():
    cfg, _, _ = _build()
    assert cfg.budget["test_budget"] is False and cfg.budget["pacing"] == "even"


def test_fields_and_creatives():
    cfg, pubs, personas = _build()
    assert cfg.conversion_event == "subscription_start" and cfg.bid_strategy["target_usd"] == 42
    assert cfg.targeting["geo"] == ["US"] and cfg.targeting["personas"] == [p.persona_id for p in personas]
    assert cfg.targeting["interests"] == ["pet_food", "pet_health", "subscription"]
    assert cfg.targeting["gender"] == "all"
    assert all(li.creative_id for li in cfg.line_items)
    assert cfg.guardrails["min_impressions"] == 2000
    assert cfg.decision_trace["publisher_fits"] == {p.publisher_id: p.fit for p in pubs}
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
    assert cfg.targeting["age_range"] == [50, T.audience.age_ceiling]
    assert "None" not in cfg.rationales["targeting"]
    assert f"ages 50-{T.audience.age_ceiling}" in cfg.rationales["targeting"]
    b = B.model_copy(update={"age_min": None, "age_max": 35})
    cfg, _, _ = _build(b=b)
    assert cfg.targeting["age_range"] == [T.audience.age_floor, 35]


def test_budget_defaults_to_recommended_with_source():
    cfg, pubs, _ = _build(monthly=None)
    rec = recommended_budget(B, pubs, CAT, False, T)
    assert cfg.budget["monthly_usd"] == cfg.budget["recommended_usd"] == rec.usd
    assert cfg.budget["source"] == "recommended"
    r = cfg.rationales["budget"]
    # the inputs: target CPA, conversions per line item, publisher count, rounding unit
    assert "$42" in r and "50 conversions" in r and f"{len(pubs)} publishers" in r and "$500" in r


def test_user_budget_wins_and_rationale_names_both():
    cfg, pubs, _ = _build(monthly=25000)
    rec = recommended_budget(B, pubs, CAT, False, T)
    assert cfg.budget["monthly_usd"] == 25000 and cfg.budget["source"] == "user"
    assert cfg.budget["recommended_usd"] == rec.usd
    assert "$25,000" in cfg.rationales["budget"] and f"${rec.usd:,.0f}" in cfg.rationales["budget"]


def test_frequency_and_pacing_in_config_with_rationales():
    cfg, _, _ = _build()  # premium subscription: 3/14 + 1
    assert cfg.frequency_cap == {"impressions": 4, "per_days": 14}
    f = cfg.rationales["frequency_cap"]
    assert "premium" in f and "subscription" in f and "4" in f and "14" in f
    weak, _, _ = _build(weak_fit=True)
    assert weak.frequency_cap == {"impressions": 3, "per_days": 14}
    assert "test" in weak.rationales["frequency_cap"]
    assert cfg.budget["pacing"] == "even" and "premium" in cfg.rationales["pacing"]
    assert weak.budget["pacing"] == "front_loaded" and "test" in weak.rationales["pacing"]


def test_pacing_accelerated_for_mid_tier_below_recommendation():
    b = B.model_copy(update={"price_tier": "mid", "business_model": "one_off"})
    cfg, pubs, _ = _build(b=b, monthly=500)
    assert recommended_budget(b, pubs, CAT, False, T).usd > 500
    assert cfg.budget["pacing"] == "accelerated" and "below" in cfg.rationales["pacing"]


def test_weak_fit_rationale_names_the_minimum_floor():
    b = B.model_copy(update={"price_usd": 10, "business_model": "one_off"})
    cfg, pubs, _ = _build(weak_fit=True, monthly=None, b=b)
    rec = recommended_budget(b, pubs, CAT, True, T)
    assert rec.full_usd * T.budget.weak_fit_test_fraction < T.budget.min_usd == rec.usd
    assert "raised to the $500 minimum" in cfg.rationales["budget"]
    plain, _, _ = _build(weak_fit=True, monthly=None)
    assert "minimum" not in plain.rationales["budget"]


def test_every_creative_is_in_rotation_on_its_own_publisher():
    pubs, personas, _ = _inputs()
    # more personas than publishers: two ads written for the first publisher
    creatives = [Creative(creative_id=f"cr_{p.persona_id}", persona_id=p.persona_id,
                          publisher_id=pubs[min(i, 1) % len(pubs)].publisher_id,
                          headline="h", body="b", cta="c", why="w") for i, p in enumerate(personas)]
    cfg = build_config(brief=B, gate=GATE, publishers=pubs, personas=personas, creatives=creatives,
                       monthly_usd=None, weak_fit=False, catalog=CAT, t=T)
    placed = {c for li in cfg.line_items for c in [li.creative_id, *li.extra_creative_ids]}
    assert placed == {c.creative_id for c in creatives}
    for li in cfg.line_items:
        own = [c.creative_id for c in creatives if c.publisher_id == li.publisher_id]
        if own:
            assert [li.creative_id, *li.extra_creative_ids] == own
    assert "rotate" in cfg.rationales["line_items"]
    single, _, _ = _build()
    assert all(li.extra_creative_ids == [] for li in single.line_items)
    assert "rotate" not in single.rationales["line_items"]


def test_guardrail_limit_is_one_rounded_value():
    b = B.model_copy(update={"price_usd": 60, "business_model": "one_off"})  # CPA $21 x 1.5 = 31.5
    cfg, _, _ = _build(b=b)
    assert cfg.guardrails["cpa_limit_usd"] == 32
    assert "exceeds $32 " in cfg.rationales["guardrails"]


def test_weak_fit_rationale_states_the_test_cap():
    b = B.model_copy(update={"price_usd": 1000, "business_model": "one_off"})
    pubs, personas, creatives = _inputs()
    cfg = build_config(brief=b, gate=GATE, publishers=pubs, personas=personas, creatives=creatives,
                       monthly_usd=None, weak_fit=True, catalog=CAT, t=T)
    rec = recommended_budget(b, pubs, CAT, True, T)
    assert rec.usd == T.budget.weak_fit_test_max_usd == 3000
    assert cfg.budget["monthly_usd"] == 3000
    r = cfg.rationales["budget"]
    assert "capped at $3,000" in r and "20%" in r
    lux = build_config(brief=b.model_copy(update={"price_tier": "luxury"}), gate=GATE, publishers=pubs,
                       personas=personas, creatives=creatives, monthly_usd=None, weak_fit=True,
                       catalog=CAT, t=T)
    assert lux.frequency_cap == {"impressions": 1, "per_days": 14}
    assert "shortened to 14 days" in lux.rationales["frequency_cap"]
    assert lux.rationales["frequency_cap"].startswith("At most 1 impression per person")


def test_targeting_rationale_never_prints_none_ages():
    cfg = build_config(brief=B, gate=GATE, publishers=_inputs()[0], personas=[], creatives=[],
                       monthly_usd=None, weak_fit=False, catalog=CAT, t=T)
    assert cfg.targeting["age_range"] == [None, None]
    assert "None" not in cfg.rationales["targeting"]
    assert "all ages" in cfg.rationales["targeting"]


def test_line_items_rationale_names_reused_ads():
    pubs, personas, _ = _inputs()
    assert len(pubs) >= 2
    # one ad only, written for the first publisher: the others reuse it
    c = Creative(creative_id="cr_x", persona_id=personas[0].persona_id,
                 publisher_id=pubs[0].publisher_id, headline="h", body="b", cta="c", why="w")
    cfg = build_config(brief=B, gate=GATE, publishers=pubs, personas=personas, creatives=[c],
                       monthly_usd=None, weak_fit=False, catalog=CAT, t=T)
    r = cfg.rationales["line_items"]
    name = personas[0].name.removeprefix("The ")
    assert f"{pubs[1].name} reuses the {name} ad written for {pubs[0].name}" in r
    assert "the The" not in r


def test_budget_block_is_typed_but_json_shape_unchanged():
    import pytest
    from pydantic import ValidationError
    cfg, _, _ = _build()
    assert isinstance(cfg.budget, dict)
    assert set(cfg.model_dump(mode="json")["budget"]) == {
        "monthly_usd", "recommended_usd", "source", "pacing", "unallocated_usd", "test_budget"}
    bad = cfg.model_dump()
    bad["budget"]["pacing"] = "sideways"
    with pytest.raises(ValidationError):
        CampaignConfig.model_validate(bad)
