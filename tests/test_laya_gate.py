"""LayaGate mapping, tested with a stub agent (no download). Real-model checks are marked `laya`."""
from __future__ import annotations

import importlib.util

import pytest

from app.gate import get_gate
from app.gate import laya_gate
from app.gate.laya_gate import LayaGate, load_questions
from app.models import GateResult
from app.tuning import LayaThresholds, load_tuning
from tests.conftest import brief

T = load_tuning()
PRIMARIES = {"instant_delivery", "apparel", "wellness_services", "pet", "groceries", "wellness_dtc",
             "beauty", "home", "meal_kits", "beverages"}


class StubAgent:
    def __init__(self, *, has=0.9, buyer=None, ident=0.8, cat="pet"):
        buyer = buyer or {"consumer": 0.7, "business": 0.1, "not_shoppable": 0.1, "unclear": 0.1}
        self.answers = {
            "has_content": {"type": "noul", "noul": has},
            "buyer": {"type": "choice", "choice": max(buyer, key=buyer.get), "probabilities": buyer},
            "product_identifiable": {"type": "noul", "noul": ident},
            "category": {"type": "choice", "choice": cat, "probabilities": {cat: 0.6}},
        }
        self.calls = []

    def predict(self, state, questions):
        self.calls.append((state, questions))
        return {"answers": self.answers}


def _tuning(laya: LayaThresholds | None = None, **gate):
    g = T.gate.model_copy(update={"laya": laya, **gate})
    return T.model_copy(update={"gate": g})


def _assess(agent, b=None, tuning=None) -> GateResult:
    return LayaGate(tuning or _tuning(), agent=agent).assess("text", b or brief(categories=["pet_food"]))


def test_state_and_questions_passed_to_agent():
    a = StubAgent()
    LayaGate(T, agent=a).assess("We sell dog food", brief(categories=["pet_food"]))
    state, qs = a.calls[0]
    assert state == {"advertiser_text": "We sell dog food", "brief_categories": ["pet_food"]}
    assert set(qs) == {"has_content", "buyer", "product_identifiable", "category"}


def test_mapping_when_category_agrees():
    r = _assess(StubAgent(has=0.9, ident=0.8, cat="pet"))  # pet_food is a pet subcategory
    assert r.impl == "laya"
    assert r.signals["has_content"] == 0.9
    assert r.signals["business_prob"] == pytest.approx(0.2)  # business + not_shoppable
    assert r.signals["clarity"] == pytest.approx(0.8)
    assert r.signals["category_agrees"] == 1.0


def test_disagreement_factor_scales_clarity():
    r = _assess(StubAgent(ident=0.8, cat="beauty"))
    f = T.gate.category_disagreement_factor
    assert r.signals["clarity"] == pytest.approx(0.8 * f)
    assert r.signals["category_agrees"] == 0.0
    assert r.signals["category"] == "beauty"


def test_adjacent_category_counts_as_agreement():
    b = brief(categories=["pet_food"], adjacent_categories=["groceries"])
    assert _assess(StubAgent(ident=0.8, cat="groceries"), b).signals["clarity"] == pytest.approx(0.8)


def test_other_agrees_only_with_an_empty_brief():
    assert _assess(StubAgent(ident=0.8, cat="other"), brief()).signals["category_agrees"] == 1.0
    assert _assess(StubAgent(ident=0.8, cat="other")).signals["category_agrees"] == 0.0
    assert _assess(StubAgent(ident=0.8, cat="pet"), brief()).signals["category_agrees"] == 0.0


def test_not_shoppable_goes_out_of_scope():
    buyer = {"consumer": 0.1, "business": 0.2, "not_shoppable": 0.6, "unclear": 0.1}
    r = _assess(StubAgent(buyer=buyer))
    assert r.signals["business_prob"] == pytest.approx(0.8)
    assert r.outcome == "out_of_scope"


def test_low_has_content_is_no_signal():
    assert _assess(StubAgent(has=0.1)).outcome == "no_signal"


def test_signals_include_every_raw_probability():
    s = _assess(StubAgent()).signals
    for k in ("p_has_content", "p_product_identifiable", "buyer_consumer", "buyer_business",
              "buyer_not_shoppable", "buyer_unclear", "buyer", "category", "category_prob"):
        assert k in s, k


def test_uses_laya_thresholds_and_falls_back_to_gate():
    a = StubAgent(ident=0.6)
    # gate.proceed_threshold 0.70 -> clarify without a laya block
    assert _assess(a, tuning=_tuning(None)).outcome == "clarify"
    laya = LayaThresholds(proceed_threshold=0.5, no_signal_threshold=0.3, business_threshold=0.5)
    r = _assess(a, tuning=_tuning(laya))
    assert r.outcome == "proceed" and r.threshold == 0.5


def test_question_file_matches_catalog_and_buyer_types():
    qs = load_questions()
    assert qs["has_content"]["type"] == "noul" and qs["product_identifiable"]["type"] == "noul"
    assert set(qs["buyer"]["criteria"]) == {"consumer", "business", "not_shoppable", "unclear"}
    assert set(qs["category"]["criteria"]) == PRIMARIES | {"other"}


def test_get_gate_laya_uses_lazy_singleton(monkeypatch):
    stub = StubAgent()
    monkeypatch.setattr(laya_gate, "_load_agent", lambda: stub)
    monkeypatch.setattr(laya_gate, "_AGENT", None)
    g = get_gate("laya", tuning=T)
    assert isinstance(g, LayaGate) and g.agent is stub
    assert get_gate("laya", tuning=T).agent is stub  # loaded once


def test_tuning_has_laya_block():
    assert T.gate.laya is not None
    assert 0 < T.gate.laya.proceed_threshold < 1


_HAS_LAYA = importlib.util.find_spec("laya") is not None


@pytest.mark.laya
@pytest.mark.skipif(not _HAS_LAYA, reason="laya not installed (uv sync --group laya)")
def test_real_model_returns_probabilities():
    g = get_gate("laya", tuning=T)
    r = g.assess("We sell grain-free dog food for senior dogs, $54 a bag, monthly subscription.",
                 brief(categories=["pet_food"]))
    for k in ("has_content", "business_prob", "clarity"):
        assert 0.0 <= r.signals[k] <= 1.0
    empty = g.assess("idk just try it", brief(describes_business=False))
    assert empty.signals["has_content"] < r.signals["has_content"]
