"""Golden snapshot of step 1 and the no-note config for every eval case: the refactor must not
change a single number.

    uv run python -m scripts.golden --write   # record (cached LLM; live only on a cache miss)
    uv run python -m scripts.golden --check   # compare (cache only; a miss is a failure)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.llm import CachedProvider, LLMError, OpenAIProvider
from app.loaders import load_catalog, load_tuning
from app.pipeline import make_config, stage1

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "cases.jsonl"
GOLDEN = ROOT / "tests" / "golden_cases.jsonl"
CACHE = ROOT / ".cache" / "llm"
DROPPED = {"stage_token", "mode", "agent_trace", "agent_notes", "notes", "creatives", "config",
           "impl", "signals", "decision_trace", "conversions_goal"}


class CacheOnly:
    """The inner provider for --check: any cache miss fails instead of calling the model."""

    def parse(self, *, system, user, schema, model):
        raise LLMError(f"cache miss for {schema.__name__}")


def _clean(value):
    if isinstance(value, dict):
        if "creative_id" in value and "publisher_id" in value and "share" in value:
            value = {**value, "ads": [value["creative_id"], *value["extra_creative_ids"]]
                     if value["creative_id"] else []}
            value = {k: v for k, v in value.items() if k not in ("creative_id", "extra_creative_ids")}
        return {k: _clean(v) for k, v in value.items() if k not in DROPPED}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def snapshot(case: dict, llm, catalog, tuning) -> dict:
    result = stage1(case["text"].strip(), None, None, None, llm=llm, catalog=catalog, tuning=tuning)
    config = None
    if result.outcome in ("proceed", "weak_fit"):
        config = make_config(result.brief, result.gate, result.publishers, result.personas, [], None,
                             catalog=catalog, t=tuning).model_dump()
    return {"id": case["id"], "stage1": _clean(result.model_dump()), "config": _clean(config)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.golden")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", dest="mode", action="store_const", const="--write")
    modes.add_argument("--check", dest="mode", action="store_const", const="--check")
    mode = parser.parse_args(argv).mode
    os.environ.pop("LLM_CACHE_DIR", None)
    inner = OpenAIProvider() if mode == "--write" else CacheOnly()
    llm = CachedProvider(inner, CACHE)
    catalog, tuning = load_catalog(ROOT / "data"), load_tuning()
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    snapshots = [snapshot(case, llm, catalog, tuning) for case in cases]
    if mode == "--write":
        GOLDEN.write_text("".join(json.dumps(s, sort_keys=True) + "\n" for s in snapshots))
        print(f"wrote {len(snapshots)} cases to {GOLDEN}")
        return 0
    golden = {s["id"]: s for s in map(json.loads, GOLDEN.read_text().splitlines())}
    for current in snapshots:
        if json.loads(json.dumps(current, sort_keys=True)) != golden.get(current["id"]):
            print(f"differs: {current['id']}")
            return 1
    print(f"all {len(snapshots)} cases match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
