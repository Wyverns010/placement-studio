"""Fit gate thresholds offline from evals/last_run.json (no LLM calls).

    uv run python -m evals.calibrate [--split train] [--dry-run]
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import yaml

from app.gate import decide_outcome
from app.tuning import GateTuning, load_tuning

LAST_RUN = Path("evals/last_run.json")
TUNING = Path("config/tuning.yaml")
KEYS = ("proceed_threshold", "no_signal_threshold", "business_threshold")


def _grid(lo: float, hi: float, step: float = 0.05) -> list[float]:
    return [round(lo + i * step, 2) for i in range(int(round((hi - lo) / step)) + 1)]


GRIDS = {"proceed_threshold": _grid(0.40, 0.90), "no_signal_threshold": _grid(0.10, 0.50),
         "business_threshold": _grid(0.30, 0.80)}


def redecide(rec: dict, g: GateTuning) -> str:
    s = rec["signals"]
    r = decide_outcome(has_content=s["has_content"], business_prob=s["business_prob"],
                       clarity=s["clarity"], t=g, impl="llm", signals={})
    if r.outcome == "proceed" and rec.get("weak_fit_if_proceed"):
        return "weak_fit"
    return r.outcome


def accuracy(recs: list[dict], g: GateTuning) -> float:
    if not recs:
        return 0.0
    return sum(1 for r in recs if redecide(r, g) in r["expected"]) / len(recs)


def fit(records: list[dict], current: GateTuning, *, split: str = "train") -> tuple[dict, float]:
    recs = [r for r in records if r.get("signals") and (split == "all" or r["split"] == split)]
    cur = {k: getattr(current, k) for k in KEYS}
    best, best_key = None, None
    for combo in itertools.product(*(GRIDS[k] for k in KEYS)):
        cand = dict(zip(KEYS, combo))
        acc = accuracy(recs, current.model_copy(update=cand))
        dist = sum(abs(cand[k] - cur[k]) for k in KEYS)
        key = (-acc, dist)
        if best_key is None or key < best_key:
            best, best_key = cand, key
    return best, -best_key[0]


def write_tuning(path: Path, values: dict) -> None:
    data = yaml.safe_load(Path(path).read_text())
    for k in KEYS:
        data["gate"][k] = values[k]
    Path(path).write_text(yaml.dump(data, sort_keys=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.calibrate")
    ap.add_argument("--split", choices=["train", "test", "all"], default="train")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--runs", type=Path, default=LAST_RUN)
    ap.add_argument("--tuning", type=Path, default=TUNING)
    a = ap.parse_args(argv)

    t = load_tuning(a.tuning)
    records = json.loads(a.runs.read_text())
    recs = [r for r in records if r.get("signals") and (a.split == "all" or r["split"] == a.split)]
    if not recs:
        print(f"no usable records for split {a.split!r} in {a.runs}", file=sys.stderr)
        return 1
    before = accuracy(recs, t.gate)
    best, after = fit(records, t.gate, split=a.split)
    print(f"split={a.split} n={len(recs)}")
    print(f"before: {', '.join(f'{k}={getattr(t.gate, k)}' for k in KEYS)}  accuracy {before:.1%}")
    print(f"after:  {', '.join(f'{k}={best[k]}' for k in KEYS)}  accuracy {after:.1%}")
    if a.dry_run:
        print("dry run: config not written")
    else:
        write_tuning(a.tuning, best)
        print(f"wrote {a.tuning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
