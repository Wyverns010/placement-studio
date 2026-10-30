import pytest

from app.gate import decide_outcome, get_gate
from app.gate.llm_gate import LLMSelfReportGate
from app.models import Brief
from app.tuning import load_tuning


def _brief(**kw) -> Brief:
    base = dict(
        describes_business=True, product="x", audience_type="consumer",
        categories=[], adjacent_categories=[], conflicts=[], price_usd=None,
        price_tier="unknown", business_model="unknown", age_min=None,
        age_max=None, gender_skew="unknown", facts=[], unknowns=[],
        self_confidence=0.9,
    )
    base.update(kw)
    return Brief(**base)


T = load_tuning().gate


@pytest.mark.parametrize(
    "has_content,business_prob,clarity,expected",
    [
        (0.29, 0.0, 0.9, "no_signal"),
        (0.30, 0.0, 0.9, "proceed"),
        (0.30, 0.50, 0.9, "out_of_scope"),
        (1.0, 0.49, 0.9, "proceed"),
        (1.0, 0.0, 0.69, "clarify"),
        (1.0, 0.0, 0.70, "proceed"),
    ],
)
def test_decide_outcome_branches(has_content, business_prob, clarity, expected):
    r = decide_outcome(has_content=has_content, business_prob=business_prob,
                       clarity=clarity, t=T, impl="llm", signals={})
    assert r.outcome == expected
    assert r.confidence == clarity
    assert r.threshold == T.proceed_threshold


def test_decide_outcome_signals_and_clamp():
    r = decide_outcome(has_content=1.0, business_prob=0.0, clarity=1.2,
                       t=T, impl="llm", signals={"a": "b"})
    assert r.confidence == 1.0 and r.outcome == "proceed"
    assert r.signals["has_content"] == 1.0
    assert r.signals["clarity"] == 1.0
    assert r.signals["business_prob"] == 0.0
    assert r.signals["a"] == "b"


def test_llm_gate_maps_business_brief_to_out_of_scope():
    r = LLMSelfReportGate(load_tuning()).assess("x", _brief(audience_type="business"))
    assert r.outcome == "out_of_scope" and r.impl == "llm"


def test_llm_gate_no_signal_and_clarify_and_proceed():
    g = LLMSelfReportGate(load_tuning())
    assert g.assess("x", _brief(describes_business=False)).outcome == "no_signal"
    assert g.assess("x", _brief(self_confidence=0.4)).outcome == "clarify"
    assert g.assess("x", _brief()).outcome == "proceed"
    assert g.assess("x", _brief(audience_type="unclear")).outcome == "out_of_scope"


def test_get_gate(monkeypatch):
    monkeypatch.delenv("GATE_IMPL", raising=False)
    assert isinstance(get_gate(), LLMSelfReportGate)
    monkeypatch.setenv("GATE_IMPL", "laya")
    with pytest.raises(NotImplementedError):
        get_gate()
    with pytest.raises(ValueError):
        get_gate("bogus")
