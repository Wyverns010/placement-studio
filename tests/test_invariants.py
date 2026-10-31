from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.gate import get_gate
from app.llm import FakeProvider
from app.models import CampaignResult
from app.pipeline import run_full
from evals import calibrate
from evals.invariants import check
from evals.run import load_cases, run_cases, split_for, summarize
from tests.conftest import CAT, T
from tests.test_pipeline import CLARIFY, _creatives, brief_obj, fake

SEED = Path("tests/fixtures/seed_cases.jsonl")


def result_for(llm, text="We sell dog food") -> CampaignResult:
    return run_full(text, None, llm=llm, gate=get_gate("llm", tuning=T), catalog=CAT, t=T)


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
    assert 0.10 <= best["no_signal_threshold"] <= 0.50
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


def test_write_tuning_is_byte_identical_except_values(tmp_path):
    src = Path("config/tuning.yaml").read_text()
    assert "#" in src and "{" in src
    p = tmp_path / "tuning.yaml"
    p.write_text(src)
    calibrate.write_tuning(p, {"proceed_threshold": 0.55, "no_signal_threshold": 0.2,
                               "business_threshold": 0.6})
    a, b = src.splitlines(), p.read_text().splitlines()
    assert len(a) == len(b)
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert [y.strip() for _, y in diff] == [
        "proceed_threshold: 0.55", "no_signal_threshold: 0.2", "business_threshold: 0.6"]


def test_load_cases_rejects_wrong_split(tmp_path):
    import pytest
    row = json.loads(SEED.read_text().splitlines()[0])
    row["split"] = "test" if row["split"] == "train" else "train"
    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match=row["id"]):
        load_cases(p, split="all")


def test_confusion_diagonal_when_outcome_in_expected():
    recs = [{"id": "a", "split": "train", "expected": ["proceed", "weak_fit"], "outcome": "weak_fit",
             "recommended_ids": [], "must_publishers": [], "must_not_publishers": [],
             "invariant_failures": []}]
    assert summarize(recs)["confusion"]["weak_fit"] == {"weak_fit": 1}


def test_run_cases_counts_creative_retries_and_truncates_like_api():
    seen = []

    def brief_cb(system, user):
        seen.append(user)
        return brief_obj()

    calls = {"n": 0}

    def creatives(system, user):
        calls["n"] += 1
        out = _creatives(system, user)
        if "previous ad broke the rules" not in user and calls["n"] == 1:
            for it in out.items:
                it.headline = "Save 99% today"  # number not in the input -> one retry
        return out

    llm = FakeProvider({"BriefSchema": brief_cb, "CreativeBatch": creatives, "ClarifyBatch": CLARIFY})
    case = {"id": "x", "group": "x", "split": split_for("x"), "expected": ["proceed"],
            "text": "We sell dog food. " + "z" * 3000}
    [rec] = run_cases([case], llm=llm, gate=get_gate("llm", tuning=T), catalog=CAT, t=T,
                      concurrency=1)
    assert len(seen[0]) < 1500 + 200  # wrapped text, truncated to input.max_chars
    assert rec["creative_retries"] == 1
    assert rec["creative_calls"] == len(rec["persona_ids"]) + 1
    s = summarize([rec])
    assert s["retry_rate"] == 1 / len(rec["persona_ids"])
    assert s["latency_p50"] is not None


def test_invariants_flag_duplicate_headlines():
    r = result_for(fake())
    assert len(r.creatives) >= 2
    dup = [c.model_copy(update={"headline": "Same  thing!"}) for c in r.creatives[:2]]
    dup[1] = dup[1].model_copy(update={"headline": "same thing"})
    bad = r.model_copy(update={"creatives": dup + r.creatives[2:]})
    assert any("headline" in f and "duplicate" in f for f in check(bad, T))


def test_invariants_flag_bad_budget_and_frequency():
    r = result_for(fake())
    for update, word in [({"source": "guess"}, "source"), ({"recommended_usd": 1}, "recommended_usd"),
                         ({"pacing": "fast"}, "pacing")]:
        cfg = r.config.model_copy(update={"budget": {**r.config.budget, **update}})
        assert any(word in f for f in check(r.model_copy(update={"config": cfg}), T)), word
    cfg = r.config.model_copy(update={"frequency_cap": {"impressions": 0, "per_days": 7}})
    assert any("frequency" in f for f in check(r.model_copy(update={"config": cfg}), T))


def test_invariants_flag_creative_missing_from_line_items():
    r = result_for(fake())
    items = [li.model_copy(update={"creative_id": None, "extra_creative_ids": []}) for li in r.config.line_items]
    bad = r.model_copy(update={"config": r.config.model_copy(update={"line_items": items})})
    assert any("not in any line item" in f for f in check(bad, T))
