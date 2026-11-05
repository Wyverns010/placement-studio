import pytest

from app.gate import decide_outcome, get_gate
from app.gate.llm_gate import LLMSelfReportGate
from app.loaders import load_tuning
from tests.conftest import brief

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


@pytest.mark.parametrize("brief_kw,expected", [
    (dict(audience_type="business"), "out_of_scope"),
    # local in-person services, job ads, charities, political messages: nothing a shopper buys online
    (dict(audience_type="not_shoppable"), "out_of_scope"),
    (dict(describes_business=False), "no_signal"),
    (dict(self_confidence=0.4), "clarify"),
    (dict(), "proceed"),
    (dict(audience_type="unclear", self_confidence=0.4), "clarify"),
    (dict(audience_type="unclear", self_confidence=0.85), "proceed"),
])
def test_llm_gate_maps_brief_self_report(brief_kw, expected):
    r = LLMSelfReportGate(load_tuning()).assess("x", brief(**brief_kw))
    assert r.outcome == expected and r.impl == "llm"


def test_get_gate():
    assert isinstance(get_gate(), LLMSelfReportGate)
    with pytest.raises(ValueError):
        get_gate("bogus")
