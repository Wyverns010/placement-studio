from __future__ import annotations

import json

from app.llm import FakeProvider
from evals import generate


def _fake():
    return FakeProvider({"CandidateBatch": generate.CandidateBatch.model_validate({"items": [
        {"text": "We sell socks", "expected": "proceed", "rationale": "apparel"},
        {"text": "We sell hats", "expected": "proceed", "rationale": "apparel"},
    ]})})


def test_prompt_comes_from_prompt_files():
    system, user = generate.build_prompt("clear", 4, "pet")
    assert generate.BUCKETS["clear"] in system and "Write 4 distinct inputs" in system
    assert "Focus: pet." in system and "# Catalog publishers" in system
    assert user == "Draft the inputs."
    assert "Given examples" not in system
    system, _ = generate.build_prompt("paraphrase", 15, "")
    assert "Given examples" in system and "Focus:" not in system
    assert set(generate.BUCKETS) == {"clear", "weak_fit", "out_of_scope", "sensitive",
                                     "adversarial", "paraphrase"}


def test_generated_ids_unique_across_runs(tmp_path, monkeypatch):
    llm = _fake()
    monkeypatch.setattr(generate, "make_llm", lambda: llm)
    out = tmp_path / "c.jsonl"
    stamps = iter(["20261031T100000", "20261031T100001"])
    monkeypatch.setattr(generate, "_run_stamp", lambda: next(stamps))
    for _ in range(2):
        assert generate.main(["--bucket", "clear", "--n", "2", "--out", str(out)]) == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    ids = [r["id"] for r in rows]
    assert len(ids) == 4 and len(set(ids)) == 4
    assert ids[0] == "gen-clear-20261031T100000-01" and rows[0]["group"] == ids[0]
    assert llm.calls[0]["system"].startswith("You draft test inputs")


def test_eval_paths_are_anchored_on_repo_root():
    from evals import calibrate, run
    root = generate.ROOT
    assert (root / "pyproject.toml").is_file()
    assert run.CASES == root / "evals" / "cases.jsonl" and run.CASES.is_absolute()
    assert calibrate.TUNING == root / "config" / "tuning.yaml"
    assert generate.CANDIDATES.is_absolute() and generate.GIVEN.is_file()
