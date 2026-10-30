from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.gate import get_gate
from app.llm import FakeProvider
from app.models import CampaignResult
from app.pipeline import collect, run_pipeline
from evals import calibrate
from evals.invariants import check
from evals.run import load_cases, run_cases, split_for, summarize
from tests.conftest import CAT, T
from tests.test_pipeline import CLARIFY, _creatives, brief_obj, fake

SEED = Path("evals/cases.jsonl")


def result_for(llm, text="We sell dog food") -> CampaignResult:
    evs = run_pipeline(text, 25000, llm=llm, gate=get_gate("llm", tuning=T), catalog=CAT, t=T)
    return collect(evs)


def test_invariants_pass_on_valid_proceed():
    assert check(result_for(fake()), T) == []


def test_invariants_pass_on_other_outcomes():
    assert check(result_for(fake(categories=[], adjacent_categories=[], product="w")), T) == []
    assert check(result_for(fake(self_confidence=0.3)), T) == []
    assert check(result_for(fake(audience_type="business")), T) == []
    nosig = fake(describes_business=False, product=None, categories=[], adjacent_categories=[])
    assert check(result_for(nosig, "idk"), T) == []


def test_invariants_flag_config_on_clarify():
    proceed = result_for(fake())
    bad = proceed.model_copy(update={"outcome": "clarify"})
    fails = check(bad, T)
    assert any("config" in f for f in fails) and any("creative" in f for f in fails)


def test_invariants_flag_bad_shares_and_weak_fit_budget():
    r = result_for(fake())
    items = [i.model_copy(update={"share": i.share * 0.5}) for i in r.config.line_items]
    bad = r.model_copy(update={"config": r.config.model_copy(update={"line_items": items})})
    assert any("share" in f for f in check(bad, T))
    wf = r.model_copy(update={"outcome": "weak_fit"})
    assert any("test_budget" in f for f in check(wf, T))


def test_invariants_flag_fact_violation_and_persona_count():
    r = result_for(fake())
    c = r.creatives[0].model_copy(update={"headline": "Save 99% today"})
    bad = r.model_copy(update={"creatives": [c] + r.creatives[1:],
                               "personas": r.personas[:1]})
    fails = check(bad, T)
    assert any("fact" in f for f in fails) and any("persona" in f for f in fails)


def test_split_is_deterministic_by_group():
    assert split_for("pet-senior") == split_for("pet-senior")
    assert {split_for(f"g{i}") for i in range(50)} == {"train", "test"}


# ---- runner on the seed with a fake provider ----

def seed_llm():
    def brief_by_text(system, user):
        if "dental" in user.lower():
            return brief_obj(audience_type="business", product="dental software", categories=[])
        if "idk" in user.lower():
            return brief_obj(describes_business=False, product=None, categories=[],
                             adjacent_categories=[])
        return brief_obj()
    return FakeProvider({"BriefSchema": brief_by_text, "CreativeBatch": _creatives,
                         "ClarifyBatch": CLARIFY})


def test_run_cases_on_seed_with_fake():
    cases = load_cases(SEED, split="all")
    assert len(cases) == 3
    recs = run_cases(cases, llm=seed_llm(), gate=get_gate("llm", tuning=T), catalog=CAT, t=T,
                     concurrency=2)
    by = {r["id"]: r for r in recs}
    assert [r["id"] for r in recs] == [c["id"] for c in cases]
    for r in recs:
        assert r["outcome"] in r["expected"], r
        assert r["invariant_failures"] == []
        assert set(r["signals"]) >= {"has_content", "business_prob", "clarity"}
    assert isinstance(by[cases[0]["id"]]["weak_fit_if_proceed"], bool)
    s = summarize(recs)
    assert "accuracy" in s and "confusion" in s


def test_run_cases_records_error_without_aborting():
    cases = load_cases(SEED, split="all")
    llm = FakeProvider({})  # every call raises LookupError -> pipeline error event
    recs = run_cases(cases, llm=llm, gate=get_gate("llm", tuning=T), catalog=CAT, t=T,
                     concurrency=2)
    assert [r["outcome"] for r in recs] == ["error"] * 3


# ---- offline calibration on fabricated records ----

def rec(i, expected, hc, bp, cl, weak=False, split="train"):
    return {"id": i, "split": split, "expected": [expected],
            "signals": {"has_content": hc, "business_prob": bp, "clarity": cl},
            "weak_fit_if_proceed": weak}


def test_redecide_maps_proceed_to_weak_fit():
    g = T.gate.model_copy(update={"proceed_threshold": 0.5})
    assert calibrate.redecide(rec("a", "weak_fit", 0.9, 0.0, 0.8, weak=True), g) == "weak_fit"
    assert calibrate.redecide(rec("a", "proceed", 0.9, 0.0, 0.8), g) == "proceed"
    assert calibrate.redecide(rec("a", "clarify", 0.9, 0.0, 0.4), g) == "clarify"
    assert calibrate.redecide(rec("a", "no_signal", 0.1, 0.0, 0.4), g) == "no_signal"
    assert calibrate.redecide(rec("a", "out_of_scope", 0.9, 0.9, 0.9), g) == "out_of_scope"


def test_fit_thresholds_finds_separating_values():
    recs = [rec("p1", "proceed", 0.9, 0.0, 0.85), rec("p2", "proceed", 0.9, 0.0, 0.8),
            rec("c1", "clarify", 0.9, 0.0, 0.5), rec("c2", "clarify", 0.9, 0.1, 0.55),
            rec("n1", "no_signal", 0.05, 0.0, 0.2), rec("o1", "out_of_scope", 0.9, 0.75, 0.9),
            rec("t1", "proceed", 0.9, 0.0, 0.1, split="test")]
    best, acc = calibrate.fit(recs, T.gate, split="train")
    assert acc == 1.0
    assert 0.55 < best["proceed_threshold"] <= 0.80
    assert 0.05 < best["no_signal_threshold"] <= 0.50 or best["no_signal_threshold"] >= 0.10
    assert best["business_threshold"] <= 0.75


def test_write_tuning_preserves_other_keys(tmp_path):
    src = Path("config/tuning.yaml").read_text()
    p = tmp_path / "tuning.yaml"
    p.write_text(src)
    calibrate.write_tuning(p, {"proceed_threshold": 0.55, "no_signal_threshold": 0.2,
                               "business_threshold": 0.6})
    new, old = yaml.safe_load(p.read_text()), yaml.safe_load(src)
    assert new["gate"]["proceed_threshold"] == 0.55
    assert new["gate"]["category_disagreement_factor"] == old["gate"]["category_disagreement_factor"]
    assert list(new) == list(old)
    assert {k: v for k, v in new.items() if k != "gate"} == {k: v for k, v in old.items() if k != "gate"}
