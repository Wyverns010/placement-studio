from __future__ import annotations

import re

import pytest

from app.ads import write_ads
from app.brief import brief_schema
from app.constants.brief import NO_SIGNAL_QUESTIONS
from app.llm import FakeProvider, LLMError
from app.models.ads import Draft, Review
from app.models.brief import ClarifyBatch, ClarifyQuestion
from app.pipeline import run_full, stage1
from app.plan import build_config
from tests.conftest import CAT, T


def brief_obj(**over):
    base = dict(
        describes_business=True, product="dog food", audience_type="consumer",
        categories=["pet_food"], adjacent_categories=["pet"], conflicts=[],
        price_usd=None, price_tier="mid", business_model="one_off",
        age_min=None, age_max=None, gender_skew="unknown",
        facts=[], unknowns=["price"], self_confidence=0.9,
    )
    base.update(over)
    return brief_schema(CAT)(**base)


def _creatives(system: str, user: str) -> Draft:
    """A fake Copywriter: one clean draft, with a headline of its own per persona."""
    persona_id = re.search(r"persona_id: (persona_\d+)", system).group(1)
    return Draft(headline="Good food " + "xyz" * int(persona_id[-3:]), body="Made with care", cta="Shop now", why="fit")


ACCEPT = Review(accept=True, notes=[])


CLARIFY = ClarifyBatch(questions=[ClarifyQuestion(question="Price?", options=["Low", "High"])])


def fake(**brief_over) -> FakeProvider:
    return FakeProvider({"BriefSchema": brief_obj(**brief_over), "Draft": _creatives, "Review": ACCEPT,
                         "ClarifyBatch": CLARIFY})


def run(llm, text="We sell dog food", budget=None):
    return stage1(text, budget, None, None, llm=llm, catalog=CAT, tuning=T)


def full(llm, text="We sell dog food", budget=None):
    return run_full(text, budget, llm=llm, catalog=CAT, tuning=T)



def test_stage1_stops_after_match():
    llm = fake()
    r = run(llm)
    assert r.outcome == "proceed" and r.message is None
    assert r.budget_usd is None
    assert len(r.publishers) == 20 and any(p.recommended for p in r.publishers)
    assert 3 <= len(r.personas) <= 5
    assert "Draft" not in [c["schema"] for c in llm.calls]


def test_stage1_echoes_budget():
    assert run(fake(), budget=1000).budget_usd == 1000


def test_run_full_chains_creatives_and_config_at_recommended_budget():
    r, ads, config = full(fake())
    assert r.outcome == "proceed" and len(ads) == len(r.personas)
    assert config.budget.source == "recommended"
    assert config.budget.monthly_usd == config.budget.recommended_usd
    assert {a for li in config.line_items for a in li.ads} <= {c.persona_id for c in ads}


def test_run_full_user_budget_wins():
    r, _, config = full(fake(), budget=7000)
    assert r.budget_usd == 7000 and config.budget.monthly_usd == 7000
    assert config.budget.source == "user"


def test_stages_compose_like_run_full():
    llm = fake()
    s1 = run(llm)
    creatives = write_ads(s1.input_text, s1.brief, s1.publishers, s1.personas, None, llm, CAT, T)
    cfg = build_config(s1.brief, s1.publishers, s1.personas, creatives, None, CAT, T)
    _, full_ads, full_config = full(fake())
    assert [c.model_dump() for c in creatives] == [c.model_dump() for c in full_ads]
    assert cfg == full_config
    # creatives go only on recommended publishers, distinct where possible
    rec = {p.publisher_id for p in s1.publishers if p.recommended}
    assert {c.publisher_id for c in creatives} <= rec


def test_run_full_leaves_non_built_outcomes_alone():
    llm = fake(self_confidence=0.3)
    r, ads, config = full(llm)
    assert r.outcome == "clarify" and ads == [] and config is None
    assert "Draft" not in [c["schema"] for c in llm.calls]


def test_clarify_has_no_config():
    llm = fake(self_confidence=0.3)
    r = run(llm)
    assert r.outcome == "clarify"
    assert r.clarify and len(r.personas) == 1 and len(r.publishers) == 20
    assert "Draft" not in [c["schema"] for c in llm.calls]


def test_no_signal_skips_llm_creatives():
    llm = fake(describes_business=False, product=None, categories=[], adjacent_categories=[])
    r = run(llm, text="idk just try it")
    assert r.outcome == "no_signal" and r.clarify == NO_SIGNAL_QUESTIONS
    assert r.publishers == [] and r.personas == []
    assert [c["schema"] for c in llm.calls] == ["BriefSchema"]


def test_weak_fit_outcome_from_proceed_gate():
    r = run(fake(categories=[], adjacent_categories=["subscription"], product="widgets"))
    assert r.gate.outcome == "proceed"
    assert r.outcome == "weak_fit"
    rec = [p for p in r.publishers if p.recommended]
    assert len(rec) == T.publisher.weak_fit_show and all(p.stretch for p in rec)
    assert "widgets" in r.message and str(len(rec)) in r.message
    cfg = build_config(r.brief, r.publishers, r.personas, [], None, CAT, T)
    assert cfg.budget.test_budget and cfg.budget.pacing == "front_loaded"
    assert full(fake(categories=[], adjacent_categories=["subscription"], product="widgets"))[2].budget.test_budget


def test_weak_fit_with_no_related_publisher_picks_none():
    r = run(fake(categories=[], adjacent_categories=[], product="wooden toys"))
    assert r.outcome == "weak_fit" and not any(p.recommended for p in r.publishers)
    assert "Nothing in this catalog fits wooden toys" in r.message


def test_out_of_scope_all_excluded():
    r = run(fake(audience_type="business", product="dental software"))
    assert r.outcome == "out_of_scope"
    assert len(r.publishers) == 20 and not any(p.recommended for p in r.publishers)
    assert all(p.reason for p in r.publishers)
    assert "business buyers" in r.message and "dental software" in r.message


def test_out_of_scope_message_for_not_shoppable_does_not_claim_business_buyers():
    r = run(fake(audience_type="not_shoppable", product="emergency plumbing"))
    assert r.outcome == "out_of_scope"
    assert "business buyers" not in r.message
    assert "emergency plumbing" in r.message and "shoppers" in r.message


def test_out_of_scope_message_falls_back_without_product():
    r = run(fake(audience_type="business", product=None))
    assert "this product" in r.message


def test_llm_failure_raises_for_the_api_to_map():
    with pytest.raises(LLMError):
        run(FakeProvider({"BriefSchema": LLMError("sk-secret leaked")}))



def test_run_full_returns_no_ads_when_every_draft_fails():
    llm = FakeProvider({"BriefSchema": brief_obj(), "Draft": LLMError("x")})
    result, ads, _ = full(llm)
    assert result.outcome == "proceed" and ads == []
