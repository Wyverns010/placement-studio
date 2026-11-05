"""Fit the gate's three thresholds on the train split of the last eval run (no LLM calls).

    uv run python -m evals.calibrate [--split train|test|all]

It prints the best values; copy them into app/models/tuning.py by hand.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys

from app.brief import decide
from app.models.tuning import GateTuning, Tuning
from evals.run import LAST_RUN

RANGES = {"proceed_threshold": (0.40, 0.90), "no_signal_threshold": (0.10, 0.50), "business_threshold": (0.30, 0.80)}
GRIDS = {key: [round(low + i * 0.05, 2) for i in range(round((high - low) / 0.05) + 1)]
         for key, (low, high) in RANGES.items()}


def accuracy(records: list[dict], gate: GateTuning) -> float:
    """How many stored cases the gate gets right with these thresholds."""
    if not records:
        return 0.0
    correct = 0
    for record in records:
        signals = record["signals"]
        outcome = decide(signals["has_content"], signals["business_prob"], signals["clarity"], gate).outcome
        if outcome == "proceed" and record["weak_fit_if_proceed"]:
            outcome = "weak_fit"
        correct += outcome in record["expected"]
    return correct / len(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.calibrate")
    parser.add_argument("--split", choices=["train", "test", "all"], default="train")
    split = parser.parse_args(argv).split
    current = Tuning().gate
    records = [r for r in json.loads(LAST_RUN.read_text()) if r.get("signals") and split in ("all", r["split"])]
    if not records:
        print(f"no records for split {split!r} in {LAST_RUN}; run evals.run first", file=sys.stderr)
        return 1
    # most accurate first; among ties, the one closest to today's values
    best = max(itertools.product(*GRIDS.values()), key=lambda values: (
        accuracy(records, current.model_copy(update=dict(zip(GRIDS, values)))),
        -sum(abs(value - getattr(current, key)) for key, value in zip(GRIDS, values))))
    found = dict(zip(GRIDS, best))
    print(f"split={split} n={len(records)}")
    print(f"now:  {current.model_dump()}  accuracy {accuracy(records, current):.1%}")
    print(f"best: {found}  accuracy {accuracy(records, current.model_copy(update=found)):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
