"""Run the labelled eval set through the pipeline and report accuracy.

    uv run python -m evals.run [--gate llm|laya] [--split train|test|all] [--concurrency 8]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.catalog import load_catalog
from app.gate import get_gate
from app.match import is_weak_fit, score_publishers
from app.pipeline import collect, run_pipeline
from app.tuning import load_tuning
from evals.invariants import check

CASES = Path("evals/cases.jsonl")
LAST_RUN = Path("evals/last_run.json")
OUTCOMES = ["proceed", "weak_fit", "clarify", "out_of_scope", "no_signal"]
COLS = OUTCOMES + ["error"]


def split_for(group: str) -> str:
    return "train" if int(hashlib.sha1(group.encode()).hexdigest(), 16) % 10 < 7 else "test"


def load_cases(path: Path = CASES, *, split: str = "train", only: set[str] | None = None) -> list[dict]:
    cases = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    for c in cases:
        if c["split"] != split_for(c["group"]):
            raise ValueError(f"case {c['id']}: split {c['split']!r} != split_for(group) "
                             f"{split_for(c['group'])!r}")
    if split != "all":
        cases = [c for c in cases if c["split"] == split]
    if only:
        cases = [c for c in cases if c["id"] in only]
    return cases


class _CallCounter:
    """Per-case LLM wrapper that counts calls by schema name (creative retries = extra calls)."""

    def __init__(self, inner):
        self.inner = inner
        self.calls: Counter = Counter()

    def parse(self, *, system, user, schema, model):
        self.calls[schema.__name__] += 1
        return self.inner.parse(system=system, user=user, schema=schema, model=model)


class _TimedGate:
    """Per-case gate wrapper that records how long assess() took."""

    def __init__(self, inner):
        self.inner = inner
        self.seconds = 0.0

    def assess(self, text, brief):
        start = time.perf_counter()
        try:
            return self.inner.assess(text, brief)
        finally:
            self.seconds += time.perf_counter() - start


def _run_one(case: dict, llm, gate, catalog, t) -> dict:
    rec = {"id": case["id"], "split": case["split"], "expected": case["expected"],
           "must_publishers": case.get("must_publishers", []),
           "must_not_publishers": case.get("must_not_publishers", []),
           "outcome": "error", "signals": {}, "weak_fit_if_proceed": False,
           "recommended_ids": [], "persona_ids": [], "invariant_failures": [],
           "latency_s": 0.0, "creative_calls": 0, "creative_retries": 0, "residual_violations": 0}
    text = case["text"].strip()[: t.input.max_chars]  # same truncation as the API
    counter = _CallCounter(llm)
    timed = _TimedGate(gate)
    start = time.perf_counter()
    try:
        r = collect(run_pipeline(text, case.get("budget_usd", 25000), llm=counter, gate=timed,
                                 catalog=catalog, t=t))
        rec["outcome"] = r.outcome
        if r.gate:
            rec["gate_impl"] = r.gate.impl
            rec["signals"] = {k: v for k, v in r.gate.signals.items()
                              if k in ("has_content", "business_prob", "clarity")}
            rec["gate_signals"] = r.gate.signals
        if r.brief and r.outcome != "no_signal":
            rec["weak_fit_if_proceed"] = is_weak_fit(score_publishers(r.brief, catalog, t), t)
        rec["recommended_ids"] = [p.publisher_id for p in r.publishers if p.recommended]
        rec["persona_ids"] = [p.persona_id for p in r.personas]
        rec["invariant_failures"] = check(r, t)
        rec["creative_calls"] = counter.calls["CreativeBatch"]
        # first pass makes one call per persona; every call beyond that is a retry
        rec["creative_retries"] = max(0, rec["creative_calls"] - len(r.personas)) if rec["creative_calls"] else 0
        rec["residual_violations"] = sum(1 for c in r.creatives if c.fact_violations)
    except Exception as e:  # noqa: BLE001 - one bad case must never abort the run
        rec["error"] = f"{type(e).__name__}: {e}"[:200]
    rec["latency_s"] = round(time.perf_counter() - start, 2)
    rec["gate_latency_s"] = round(timed.seconds, 6)
    return rec


def run_cases(cases: list[dict], *, llm, gate, catalog, t, concurrency: int = 8) -> list[dict]:
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        return list(ex.map(lambda c: _run_one(c, llm, gate, catalog, t), cases))


def summarize(recs: list[dict]) -> dict:
    n = len(recs)
    correct = sum(1 for r in recs if r["outcome"] in r["expected"])
    conf = {e: Counter() for e in OUTCOMES}
    for r in recs:
        row = r["outcome"] if r["outcome"] in r["expected"] else r["expected"][0]
        conf[row][r["outcome"]] += 1
    per = {}
    for o in OUTCOMES:
        tp = sum(1 for r in recs if r["outcome"] == o and o in r["expected"])
        pred = sum(1 for r in recs if r["outcome"] == o)
        actual = sum(1 for r in recs if o in r["expected"])
        per[o] = {"precision": tp / pred if pred else None, "recall": tp / actual if actual else None,
                  "n": actual}
    built = [r for r in recs if r["outcome"] in ("proceed", "weak_fit")]

    def hit(key, want_present):
        rows = [(set(r[key]), set(r["recommended_ids"])) for r in built if r[key]]
        total = sum(len(m) for m, _ in rows)
        ok = sum(len(m & rec) if want_present else len(m - rec) for m, rec in rows)
        return ok / total if total else None

    first = sum(r.get("creative_calls", 0) - r.get("creative_retries", 0) for r in recs)
    lat = sorted(r["latency_s"] for r in recs if "latency_s" in r)
    gate_lat = [r["gate_latency_s"] for r in recs if "gate_latency_s" in r]

    def pct(q):
        return lat[min(len(lat) - 1, int(q * len(lat)))] if lat else None

    return {"n": n, "correct": correct,
            "retry_rate": sum(r.get("creative_retries", 0) for r in recs) / first if first else None,
            "residual_violations": sum(r.get("residual_violations", 0) for r in recs),
            "latency_p50": pct(0.5), "latency_p90": pct(0.9),
            "gate_latency_mean": sum(gate_lat) / len(gate_lat) if gate_lat else None,
            "accuracy": correct / n if n else 0.0, "per": per,
            "confusion": {e: dict(c) for e, c in conf.items()},
            "must_hit": hit("must_publishers", True),
            "must_not_clear": hit("must_not_publishers", False),
            "invariant_failures": {r["id"]: r["invariant_failures"] for r in recs
                                   if r["invariant_failures"]},
            "errors": [r["id"] for r in recs if r["outcome"] == "error"]}


def _pct(x) -> str:
    return "  -  " if x is None else f"{x:5.0%}"


def render(s: dict) -> str:
    L = [f"{'outcome':<13}{'prec':>6}{'recall':>8}{'n':>5}"]
    for o in OUTCOMES:
        p = s["per"][o]
        L.append(f"{o:<13}{_pct(p['precision']):>6}{_pct(p['recall']):>8}{p['n']:>5}")
    L += ["", "confusion (rows expected, cols got)", f"{'':<13}" + "".join(f"{c[:7]:>8}" for c in COLS)]
    for e in OUTCOMES:
        row = s["confusion"].get(e, {})
        L.append(f"{e:<13}" + "".join(f"{row.get(c, 0):>8}" for c in COLS))
    L += ["", f"must publishers hit (proceed/weak_fit cases):     {_pct(s['must_hit'])}",
          f"must-not publishers avoided (same cases):           {_pct(s['must_not_clear'])}", ""]
    L.append(f"creative retry rate (personas re-asked after a facts/length miss): {_pct(s['retry_rate'])}; "
             f"residual violations: {s['residual_violations']}")
    if s["latency_p50"] is not None:
        L.append(f"latency p50 {s['latency_p50']:.1f}s, p90 {s['latency_p90']:.1f}s (near 0 when cached)")
    if s.get("gate_latency_mean") is not None:
        L.append(f"gate latency mean {s["gate_latency_mean"] * 1000:.2f} ms per case")
    if s["invariant_failures"]:
        L.append("invariant failures:")
        for cid, fs in s["invariant_failures"].items():
            L += [f"  {cid}: {f}" for f in fs]
    else:
        L.append("invariant failures: none")
    if s["errors"]:
        L.append("errors: " + ", ".join(s["errors"]))
    L.append(f"total: {s['correct']}/{s['n']} correct, accuracy {s['accuracy']:.1%}")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(prog="evals.run")
    ap.add_argument("--gate", choices=["llm", "laya"], default="llm")
    ap.add_argument("--split", choices=["train", "test", "all"], default="train")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--cases", type=Path, default=CASES)
    a = ap.parse_args(argv)

    if a.no_cache:
        os.environ.pop("LLM_CACHE_DIR", None)
    else:
        os.environ.setdefault("LLM_CACHE_DIR", ".cache/llm")
    t = load_tuning()
    try:
        gate = get_gate(a.gate, tuning=t)
    except ImportError as e:
        print(f"gate {a.gate!r} is not available: {e} (uv sync --group laya)", file=sys.stderr)
        return 2
    from app.llm import get_provider

    only = {x for x in a.only.split(",") if x} or None
    cases = load_cases(a.cases, split=a.split, only=only)
    recs = run_cases(cases, llm=get_provider(), gate=gate, catalog=load_catalog(), t=t,
                     concurrency=a.concurrency)
    LAST_RUN.write_text(json.dumps(recs, indent=1))
    LAST_RUN.with_name(f"last_run_{a.gate}_{a.split}.json").write_text(json.dumps(recs, indent=1))
    print(render(summarize(recs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
