from __future__ import annotations

import re

import pytest

from app.create import NO_SIGNAL_QUESTIONS, ClarifyBatch, CreativeBatch
from app.gate import get_gate
from app.llm import FakeProvider, LLMError
from app.models import ClarifyQuestion
from app.pipeline import PipelineError, collect, run_pipeline
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
        dict(persona_id=i, headline="Good food", body="Made with care", cta="Shop now", why="fit")
        for i in ids]})


CLARIFY = ClarifyBatch(questions=[ClarifyQuestion(question="Price?", options=["Low", "High"])])


def fake(**brief_over) -> FakeProvider:
    return FakeProvider({"BriefSchema": brief_obj(**brief_over), "CreativeBatch": _creatives,
                         "ClarifyBatch": CLARIFY})


def run(llm, text="We sell dog food", budget=25000):
    return list(run_pipeline(text, budget, llm=llm, gate=get_gate("llm", tuning=T),
                             catalog=CAT, t=T))


def stages(evs):
    return [e.stage for e in evs]


def test_proceed_event_order():
    evs = run(fake())
    assert stages(evs) == ["understood", "gate", "publishers", "personas", "creatives", "config", "done"]
    r = collect(iter(evs))
    assert r.outcome == "proceed" and r.config is not None and r.message is None
    assert len(r.publishers) == 20 and any(p.recommended for p in r.publishers)
    assert 3 <= len(r.personas) <= 5 and r.creatives
    pub = evs[2].data
    assert len(pub["top"]) == 5 and pub["recommended"]
    assert evs[4].data == {"count": len(r.creatives)}


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
    evs = run(fake(categories=[], adjacent_categories=[], product="widgets"))
    assert evs[1].data["outcome"] == "proceed"
    r = collect(iter(evs))
    assert r.outcome == "weak_fit" and r.config is not None
    rec = [p for p in r.publishers if p.recommended]
    assert len(rec) == T.publisher.weak_fit_show and all(p.stretch for p in rec)
    assert "widgets" in r.message and str(len(rec)) in r.message
    assert r.config.budget["test_budget"]


def test_out_of_scope_all_excluded():
    evs = run(fake(audience_type="business", product="dental software"))
    assert stages(evs) == ["understood", "gate", "publishers", "done"]
    r = collect(iter(evs))
    assert r.outcome == "out_of_scope" and r.config is None and r.creatives == []
    assert len(r.publishers) == 20 and not any(p.recommended for p in r.publishers)
    assert all(p.reason for p in r.publishers)
    assert "business buyers" in r.message and "dental software" in r.message
    assert evs[2].data["recommended"] == []


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
    llm = FakeProvider({"BriefSchema": brief_obj(), "CreativeBatch": RuntimeError("sk-boom")})
    evs = run(llm)
    assert stages(evs)[-1] == "error" and "sk-boom" not in evs[-1].data["message"]
    assert evs[-1].data["message"] == "Something went wrong building this campaign."
