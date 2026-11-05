"""The evals: invariants every result obeys, the case runner, and the gate calibration."""
from __future__ import annotations

import json
from pathlib import Path

from app.llm import FakeProvider
from app.pipeline import run_full
from evals import calibrate
from evals.invariants import check
from evals.run import load_cases, run_case, summarize
from tests.conftest import CAT, T
from tests.test_pipeline import ACCEPT, CLARIFY, _creatives, brief_obj, fake

SEED = Path("tests/fixtures/seed_cases.jsonl")


def failures(llm, text="We sell dog food") -> list[str]:
    result, ads, config = run_full(text, None, llm=llm, catalog=CAT, tuning=T)
    return check(result, ads, config, T)


def test_invariants_pass_on_every_outcome():
    assert failures(fake()) == []
    assert failures(fake(categories=[], adjacent_categories=["subscription"], product="w")) == []
    assert failures(fake(self_confidence=0.3)) == []
    assert failures(fake(audience_type="business")) == []
    assert failures(fake(describes_business=False, product=None, categories=[], adjacent_categories=[]), "idk") == []


def test_invariants_catch_broken_results():
    result, ads, config = run_full("We sell dog food", None, llm=fake(), catalog=CAT, tuning=T)
    clarify = result.model_copy(update={"outcome": "clarify"})
    assert any("config" in f for f in check(clarify, ads, config, T))
    halved = config.model_copy(update={"line_items": [i.model_copy(update={"share": i.share / 2})
                                                      for i in config.line_items]})
    assert any("share" in f for f in check(result, ads, halved, T))
    weak = result.model_copy(update={"outcome": "weak_fit"})
    assert any("test budget" in f for f in check(weak, ads, config, T))
    few = result.model_copy(update={"personas": result.personas[:1]})
    assert any("personas" in f for f in check(few, ads, config, T))
    unplaced = config.model_copy(update={"line_items": [i.model_copy(update={"ads": []}) for i in config.line_items]})
    assert any("not in any line item" in f for f in check(result, ads, unplaced, T))


def seed_llm():
    def brief_by_text(system, user):
        if "dental" in user.lower():
            return brief_obj(audience_type="business", product="dental software", categories=[])
        if "idk" in user.lower():
            return brief_obj(describes_business=False, product=None, categories=[], adjacent_categories=[])
        return brief_obj()
    return FakeProvider({"BriefSchema": brief_by_text, "Draft": _creatives, "Review": ACCEPT, "ClarifyBatch": CLARIFY})


def test_run_case_on_the_seed_cases():
    cases = load_cases("all", SEED)
    records = [run_case(case, seed_llm(), CAT, T, stage1_only=False) for case in cases]
    assert len(records) == 3
    for record in records:
        assert record["outcome"] in record["expected"] and record["invariant_failures"] == []
        assert set(record["signals"]) == {"has_content", "business_prob", "clarity"}
    summary = summarize(records)
    assert summary["accuracy"] == 1.0 and summary["misses"] == []


def test_a_failing_case_is_recorded_and_the_run_goes_on():
    records = [run_case(case, FakeProvider({}), CAT, T, stage1_only=True) for case in load_cases("all", SEED)]
    assert [record["outcome"] for record in records] == ["error"] * 3 and all("error" in r for r in records)
    assert summarize(records)["errors"] == [case["id"] for case in load_cases("all", SEED)]


def record(expected, has_content, business_prob, clarity, weak=False, split="train"):
    return {"id": expected, "split": split, "expected": [expected], "weak_fit_if_proceed": weak,
            "signals": {"has_content": has_content, "business_prob": business_prob, "clarity": clarity}}


def test_calibration_accuracy_maps_proceed_to_weak_fit():
    gate = T.gate.model_copy(update={"proceed_threshold": 0.5})
    assert calibrate.accuracy([record("weak_fit", 0.9, 0.0, 0.8, weak=True)], gate) == 1.0
    assert calibrate.accuracy([record("clarify", 0.9, 0.0, 0.4), record("no_signal", 0.1, 0.0, 0.4),
                               record("out_of_scope", 0.9, 0.9, 0.9)], gate) == 1.0


def test_calibration_prints_separating_thresholds(tmp_path, monkeypatch, capsys):
    records = [record("proceed", 0.9, 0.0, 0.85), record("proceed", 0.9, 0.0, 0.8), record("clarify", 0.9, 0.0, 0.5),
               record("clarify", 0.9, 0.1, 0.55), record("no_signal", 0.05, 0.0, 0.2),
               record("out_of_scope", 0.9, 0.75, 0.9), record("proceed", 0.9, 0.0, 0.1, split="test")]
    last_run = tmp_path / "last_run.json"
    last_run.write_text(json.dumps(records))
    monkeypatch.setattr(calibrate, "LAST_RUN", last_run)
    assert calibrate.main(["--split", "train"]) == 0
    assert "accuracy 100.0%" in capsys.readouterr().out.splitlines()[-1]
