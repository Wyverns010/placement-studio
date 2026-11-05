"""Run the labelled cases through the app and report how often it gets them right.

    uv run python -m evals.run [--split train|test|all] [--stage1] [--no-cache]

LLM answers are cached in .cache/llm, so a re-run is free; --no-cache calls the model live.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.constants.brief import BUSINESS_PROB
from app.constants.paths import ROOT
from app.llm import CachedProvider, LLMProvider, OpenAIProvider
from app.loaders import load_catalog
from app.match import pick_publishers
from app.models.catalog import Catalog
from app.models.tuning import Tuning
from app.pipeline import run_full, stage1
from evals.invariants import check

CASES = ROOT / "evals" / "cases.jsonl"
LAST_RUN = ROOT / "evals" / "last_run.json"
MUST = ("must_publishers", "must_not_publishers", "must_personas", "must_not_personas")


def load_cases(split: str, path: Path = CASES) -> list[dict]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [case for case in cases if split == "all" or case["split"] == split]


def run_case(case: dict, llm: LLMProvider, catalog: Catalog, tuning: Tuning, stage1_only: bool) -> dict:
    """One case: its outcome, ids, the gate's three signals (for calibrate.py) and any invariant
    failures. An error is recorded; it never stops the run."""
    record = {"id": case["id"], "split": case["split"], "expected": case["expected"],
              **{key: case.get(key, []) for key in MUST}, "outcome": "error", "signals": None,
              "weak_fit_if_proceed": False, "recommended_ids": [], "persona_ids": [], "invariant_failures": [],
              "flagged_ads": 0}
    try:
        text = case["text"].strip()
        if stage1_only:
            result, ads, config = stage1(text, None, None, None, llm=llm, catalog=catalog, tuning=tuning), [], None
        else:
            result, ads, config = run_full(text, None, llm=llm, catalog=catalog, tuning=tuning)
        record.update(outcome=result.outcome, flagged_ads=sum(bool(ad.fact_violations) for ad in ads),
                      recommended_ids=[p.publisher_id for p in result.publishers if p.recommended],
                      persona_ids=[p.persona_id for p in result.personas])
        if result.brief:
            brief = result.brief
            record["signals"] = {"has_content": 1.0 if brief.describes_business else 0.0,
                                 "business_prob": BUSINESS_PROB[brief.audience_type], "clarity": result.gate.confidence}
            record["weak_fit_if_proceed"] = result.outcome != "no_signal" and pick_publishers(brief, catalog, tuning)[1]
        if not stage1_only:
            record["invariant_failures"] = check(result, ads, config, tuning)
    except Exception as error:  # noqa: BLE001 - one bad case must never stop the run
        record["error"] = f"{type(error).__name__}: {error}"[:200]
    return record


def _rate(records: list[dict], key: str, got: str, present: bool) -> float | None:
    """Share of the labelled ids found (present) or avoided (not present) on built campaigns."""
    rows = [(set(r[key]), set(r[got])) for r in records if r["outcome"] in ("proceed", "weak_fit") and r[key]]
    total = sum(len(wanted) for wanted, _ in rows)
    found = sum(len(wanted & ids) if present else len(wanted - ids) for wanted, ids in rows)
    return found / total if total else None


def summarize(records: list[dict]) -> dict:
    correct = sum(record["outcome"] in record["expected"] for record in records)
    return {"n": len(records), "correct": correct, "accuracy": correct / len(records) if records else 0.0,
            "misses": [(r["id"], r["expected"], r["outcome"]) for r in records if r["outcome"] not in r["expected"]],
            "must_hit": _rate(records, "must_publishers", "recommended_ids", True),
            "must_not_avoided": _rate(records, "must_not_publishers", "recommended_ids", False),
            "persona_hit": _rate(records, "must_personas", "persona_ids", True),
            "persona_not_avoided": _rate(records, "must_not_personas", "persona_ids", False),
            "invariant_failures": {r["id"]: r["invariant_failures"] for r in records if r["invariant_failures"]},
            "errors": [r["id"] for r in records if "error" in r],
            "flagged_ads": sum(r["flagged_ads"] for r in records)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run")
    parser.add_argument("--split", choices=["train", "test", "all"], default="train")
    parser.add_argument("--stage1", action="store_true", help="step 1 only: outcomes, publishers, personas")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)
    tuning, catalog = Tuning(), load_catalog()
    llm = OpenAIProvider(tuning.llm_timeout_s)
    if not args.no_cache:
        llm = CachedProvider(llm, Path(os.getenv("LLM_CACHE_DIR") or ROOT / ".cache" / "llm"))
    cases = load_cases(args.split)
    with ThreadPoolExecutor(max_workers=8) as pool:  # live calls: 8 cases at a time
        records = list(pool.map(lambda case: run_case(case, llm, catalog, tuning, args.stage1), cases))
    LAST_RUN.write_text(json.dumps(records, indent=1))
    summary = summarize(records)
    print(json.dumps({key: value for key, value in summary.items() if key != "misses"}, indent=1))
    for case_id, expected, got in summary["misses"]:
        print(f"miss {case_id}: expected {'/'.join(expected)}, got {got}")
    print(f"total: {summary['correct']}/{summary['n']} correct, accuracy {summary['accuracy']:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
