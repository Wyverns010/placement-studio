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


def test_weak_fit_uses_test_budget():
    cfg, _, _ = _build(weak_fit=True)
    assert cfg.budget["monthly_usd"] == 5000 and cfg.budget["test_budget"] is True


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
