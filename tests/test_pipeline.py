from __future__ import annotations

import re

import pytest

from app.create import NO_SIGNAL_QUESTIONS, CreativeBatch
from app.gate import get_gate
from app.llm import FakeProvider, LLMError
from app.models.brief import ClarifyBatch, ClarifyQuestion
from app.pipeline import (
    PipelineError,
    collect,
    make_config,
    make_creatives,
    run_full,
    run_stage1,
)
from app.understand import brief_schema
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


def _creatives(system: str, user: str) -> CreativeBatch:
    ids = re.findall(r"persona_id: (persona_\d+)", system)
    return CreativeBatch.model_validate({"items": [
        dict(persona_id=i, headline="Good food " + "xyz" * int(i[-3:]), body="Made with care", cta="Shop now", why="fit")
        for i in ids]})


CLARIFY = ClarifyBatch(questions=[ClarifyQuestion(question="Price?", options=["Low", "High"])])


def fake(**brief_over) -> FakeProvider:
    return FakeProvider({"BriefSchema": brief_obj(**brief_over), "CreativeBatch": _creatives,
                         "ClarifyBatch": CLARIFY})


def run(llm, text="We sell dog food", budget=None):
    return list(run_stage1(text, budget, llm=llm, gate=get_gate("llm", tuning=T),
                           catalog=CAT, t=T))


def full(llm, text="We sell dog food", budget=None):
    return run_full(text, budget, llm=llm, gate=get_gate("llm", tuning=T), catalog=CAT, t=T)


def stages(evs):
    return [e.stage for e in evs]


def test_stage1_stops_after_match():
    llm = fake()
    evs = run(llm)
    assert stages(evs) == ["understood", "gate", "publishers", "personas", "done"]
    r = collect(iter(evs))
    assert r.outcome == "proceed" and r.message is None
    assert r.creatives == [] and r.config is None and r.budget_usd is None
    assert len(r.publishers) == 20 and any(p.recommended for p in r.publishers)
    assert 3 <= len(r.personas) <= 5
    pub = evs[2].data
    assert len(pub["top"]) == 5 and pub["recommended"]
    assert "CreativeBatch" not in [c["schema"] for c in llm.calls]


def test_stage1_echoes_budget():
    assert collect(iter(run(fake(), budget=1000))).budget_usd == 1000


def test_run_full_chains_creatives_and_config_at_recommended_budget():
    r = full(fake())
    assert r.outcome == "proceed" and len(r.creatives) == len(r.personas)
    assert r.config.budget["source"] == "recommended"
    assert r.config.budget["monthly_usd"] == r.config.budget["recommended_usd"]
    assert {li.creative_id for li in r.config.line_items} <= {c.creative_id for c in r.creatives}


def test_run_full_user_budget_wins():
    r = full(fake(), budget=7000)
    assert r.budget_usd == 7000 and r.config.budget["monthly_usd"] == 7000
    assert r.config.budget["source"] == "user"


def test_stages_compose_like_run_full():
    llm = fake()
    s1 = collect(iter(run(llm)))
    creatives = make_creatives(s1.input_text, s1.brief, s1.publishers, s1.personas,
                               llm=llm, catalog=CAT, t=T)
    cfg = make_config(s1.brief, s1.gate, s1.publishers, s1.personas, creatives, None, catalog=CAT, t=T)
    r = full(fake())
    assert [c.model_dump() for c in creatives] == [c.model_dump() for c in r.creatives]
    assert cfg == r.config
    # creatives go only on recommended publishers, distinct where possible
    rec = {p.publisher_id for p in s1.publishers if p.recommended}
    assert {c.publisher_id for c in creatives} <= rec


def test_run_full_leaves_non_built_outcomes_alone():
    llm = fake(self_confidence=0.3)
    r = full(llm)
    assert r.outcome == "clarify" and r.creatives == [] and r.config is None
    assert "CreativeBatch" not in [c["schema"] for c in llm.calls]


def test_clarify_has_no_config():
    llm = fake(self_confidence=0.3)
    evs = run(llm)
    assert stages(evs) == ["understood", "gate", "publishers", "personas", "done"]
    r = collect(iter(evs))
    assert r.outcome == "clarify" and r.config is None and r.creatives == []
    assert r.clarify and len(r.personas) == 1 and len(r.publishers) == 20
    assert len(evs[2].data["top"]) <= 5
    assert "CreativeBatch" not in [c["schema"] for c in llm.calls]


def test_no_signal_skips_llm_creatives():
    llm = fake(describes_business=False, product=None, categories=[], adjacent_categories=[])
    evs = run(llm, text="idk just try it")
    assert stages(evs) == ["understood", "gate", "done"]
    r = collect(iter(evs))
    assert r.outcome == "no_signal" and r.clarify == NO_SIGNAL_QUESTIONS
    assert r.publishers == [] and r.personas == [] and r.config is None
    assert [c["schema"] for c in llm.calls] == ["BriefSchema"]


def test_weak_fit_outcome_from_proceed_gate():
    evs = run(fake(categories=[], adjacent_categories=["subscription"], product="widgets"))
    assert evs[1].data["outcome"] == "proceed"
    r = collect(iter(evs))
    assert r.outcome == "weak_fit" and r.config is None
    rec = [p for p in r.publishers if p.recommended]
    assert len(rec) == T.publisher.weak_fit_show and all(p.stretch for p in rec)
    assert "widgets" in r.message and str(len(rec)) in r.message
    cfg = make_config(r.brief, r.gate, r.publishers, r.personas, [], None, catalog=CAT, t=T)
    assert cfg.budget["test_budget"] and cfg.budget["pacing"] == "front_loaded"
    assert full(fake(categories=[], adjacent_categories=["subscription"], product="widgets")).config.budget["test_budget"]


def test_weak_fit_with_no_related_publisher_picks_none():
    r = collect(iter(run(fake(categories=[], adjacent_categories=[], product="wooden toys"))))
    assert r.outcome == "weak_fit" and not any(p.recommended for p in r.publishers)
    assert "Nothing in this catalog fits wooden toys" in r.message


def test_out_of_scope_all_excluded():
    evs = run(fake(audience_type="business", product="dental software"))
    assert stages(evs) == ["understood", "gate", "publishers", "done"]
    r = collect(iter(evs))
    assert r.outcome == "out_of_scope" and r.config is None and r.creatives == []
    assert len(r.publishers) == 20 and not any(p.recommended for p in r.publishers)
    assert all(p.reason for p in r.publishers)
    assert "business buyers" in r.message and "dental software" in r.message
    assert evs[2].data["recommended"] == []


def test_out_of_scope_message_for_not_shoppable_does_not_claim_business_buyers():
    r = collect(iter(run(fake(audience_type="not_shoppable", product="emergency plumbing"))))
    assert r.outcome == "out_of_scope" and r.config is None
    assert "business buyers" not in r.message
    assert "emergency plumbing" in r.message and "shoppers" in r.message


def test_out_of_scope_message_falls_back_without_product():
    r = collect(iter(run(fake(audience_type="business", product=None))))
    assert "this product" in r.message


def test_llm_failure_emits_error_event():
    llm = FakeProvider({"BriefSchema": LLMError("sk-secret leaked")})
    evs = run(llm)
    assert stages(evs) == ["error"]
    assert "sk-secret" not in evs[-1].data["message"]
    assert "didn't respond" in evs[-1].data["message"]
    with pytest.raises(PipelineError):
        collect(iter(evs))


def test_unexpected_failure_emits_generic_error_last():
    llm = FakeProvider({"BriefSchema": RuntimeError("sk-boom")})
    evs = run(llm)
    assert stages(evs)[-1] == "error" and "sk-boom" not in evs[-1].data["message"]
    assert evs[-1].data["message"] == "Something went wrong building this campaign."


def test_run_full_raises_on_creative_failure():
    llm = FakeProvider({"BriefSchema": brief_obj(), "CreativeBatch": LLMError("x")})
    with pytest.raises(LLMError):
        full(llm)
