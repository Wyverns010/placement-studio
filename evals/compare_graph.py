"""Graph matching vs the formula, stage 1 only, offline (the measurements behind
evals/GRAPH_COMPARISON.md).

    uv run python -m evals.compare_graph [--split all|train|test] [--out FILE]
    uv run python -m evals.compare_graph --sweep     # how the graph tuning was chosen (train only)

Every case runs the real stage-1 pipeline (understand -> gate -> match) twice, once per
`match.impl`, on the SAME understood brief: Understand answers come from the disk cache
(.cache/llm) and a cache miss fails the case instead of calling a model, so this costs $0.
Clarify questions are stubbed (they never change the outcome or the publishers).
"""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

from app.catalog import load_catalog
from app.create import ClarifyBatch
from app.gate import get_gate
from app.llm import CachedProvider, LLMError
from app.pipeline import BUILT, collect, run_stage1
from app.tuning import load_tuning
from evals.run import load_cases, summarize

ROOT = Path(__file__).resolve().parents[1]
IMPLS = ("formula", "graph")


class _NoLive:
    def parse(self, *, system, user, schema, model):
        if schema is ClarifyBatch:
            return ClarifyBatch(questions=[])
        raise LLMError(f"not in .cache/llm: {schema.__name__} (this eval never calls a model)")


def tuning_for(impl: str, base=None):
    t = (base or load_tuning(ROOT / "config" / "tuning.yaml")).model_copy(deep=True)
    t.match.impl = impl
    return t


def run_case(case: dict, impl: str, *, t, catalog, llm) -> dict:
    text = case["text"].strip()[: t.input.max_chars]
    rec = {"id": case["id"], "split": case["split"], "bucket": case["bucket"],
           "expected": case["expected"], "must_publishers": case.get("must_publishers", []),
           "must_not_publishers": case.get("must_not_publishers", []),
           "must_personas": case.get("must_personas", []),
           "must_not_personas": case.get("must_not_personas", []), "outcome": "error",
           "recommended_ids": [], "persona_ids": [], "invariant_failures": [], "paths": {},
           "reasons": {}, "fits": {}}
    try:
        r = collect(run_stage1(text, None, llm=llm, gate=get_gate("llm", tuning=t),
                               catalog=catalog, t=t))
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"[:200]
        return rec
    rec["outcome"] = r.outcome
    if r.outcome in BUILT:
        rec["recommended_ids"] = [p.publisher_id for p in r.publishers if p.recommended]
        rec["persona_ids"] = [p.persona_id for p in r.personas]
    for p in r.publishers:
        rec["paths"][p.publisher_id] = p.path
        rec["reasons"][p.publisher_id] = p.reason
        rec["fits"][p.publisher_id] = p.fit
    return rec


def run_all(cases: list[dict], t_base=None) -> dict[str, list[dict]]:
    catalog = load_catalog(ROOT / "data")
    llm = CachedProvider(_NoLive(), ROOT / ".cache" / "llm")
    out = {}
    for impl in IMPLS:
        t = tuning_for(impl, t_base)
        out[impl] = [run_case(c, impl, t=t, catalog=catalog, llm=llm) for c in cases]
    return out


def _jaccard(a: list[str], b: list[str]) -> float:
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _pct(x) -> str:
    return "–" if x is None else f"{x:.0%}"


def headline(recs: dict[str, list[dict]], split: str) -> dict[str, dict]:
    out = {}
    for impl in IMPLS:
        rows = [r for r in recs[impl] if split == "all" or r["split"] == split]
        out[impl] = summarize(rows)
    return out


def overlap(recs: dict[str, list[dict]], split: str, key: str) -> float | None:
    pairs = [(f, g) for f, g in zip(recs["formula"], recs["graph"])
             if (split == "all" or f["split"] == split)
             and f["outcome"] in BUILT and g["outcome"] in BUILT]
    return sum(_jaccard(f[key], g[key]) for f, g in pairs) / len(pairs) if pairs else None


def report(recs: dict[str, list[dict]], catalog) -> str:
    name = {p.id: p.name for p in catalog.publishers}
    pname = {q.id: q.name.removeprefix("The ") for q in catalog.personas}
    L = ["| split | n | outcome acc. formula | outcome acc. graph | must-hit formula | must-hit graph "
         "| must-not formula | must-not graph | rec. set overlap | persona overlap |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for split in ("train", "test", "all"):
        h = headline(recs, split)
        f, g = h["formula"], h["graph"]
        L.append(f"| {split} | {f['n']} | {f['correct']}/{f['n']} ({f['accuracy']:.1%}) "
                 f"| {g['correct']}/{g['n']} ({g['accuracy']:.1%}) | {_pct(f['must_hit'])} "
                 f"| {_pct(g['must_hit'])} | {_pct(f['must_not_clear'])} | {_pct(g['must_not_clear'])} "
                 f"| {_pct(overlap(recs, split, 'recommended_ids'))} "
                 f"| {_pct(overlap(recs, split, 'persona_ids'))} |")
    errs = [r["id"] for impl in IMPLS for r in recs[impl] if r["outcome"] == "error"]
    L.append("")
    L.append(f"errors: {', '.join(errs) or 'none'}")

    L += ["", "### The brief's 15 examples", "",
          "| case | expected | formula | graph | formula picks | graph picks | personas (formula / graph) |",
          "|---|---|---|---|---|---|---|"]
    for f, g in zip(recs["formula"], recs["graph"]):
        if f["bucket"] != "given":
            continue
        picks = lambda r: ", ".join(name[i] for i in r["recommended_ids"]) or "–"  # noqa: E731
        mark = lambda r: ("✓ " if r["outcome"] in r["expected"] else "✗ ") + r["outcome"]  # noqa: E731
        pers = lambda r: ", ".join(pname[i] for i in r["persona_ids"]) or "–"  # noqa: E731
        same = "same" if f["persona_ids"] == g["persona_ids"] else f"{pers(f)} / {pers(g)}"
        L.append(f"| {f['id']} | {'/'.join(f['expected'])} | {mark(f)} | {mark(g)} | {picks(f)} | {picks(g)} "
                 f"| {same} |")

    def bullets(a: dict, b: dict, a_name: str, b_name: str) -> list[str]:
        out = []
        for pid in [x for x in b["recommended_ids"] if x not in a["recommended_ids"]]:
            tag = (" **must**" if pid in b["must_publishers"]
                   else " **must-not**" if pid in b["must_not_publishers"] else "")
            path = "; ".join(g_by[b["id"]]["paths"].get(pid) or []) or "–"
            out.append(f"- {b['id']} ({b['split']}): {b_name} adds **{name[pid]}**{tag} "
                       f"(fit {b['fits'][pid]} vs {a['fits'][pid]} in {a_name}). Graph paths: {path}")
        return out

    g_by = {r["id"]: r for r in recs["graph"]}
    adds, drops = [], []
    for f, g in zip(recs["formula"], recs["graph"]):
        if f["outcome"] in BUILT and g["outcome"] in BUILT:
            adds += bullets(f, g, "formula", "graph")
            drops += bullets(g, f, "graph", "formula")
    flips = [f"- {f['id']} ({f['split']}): expected {'/'.join(f['expected'])}, formula {f['outcome']}, "
             f"graph {g['outcome']}"
             for f, g in zip(recs["formula"], recs["graph"]) if f["outcome"] != g["outcome"]]
    L += ["", f"### Outcome changes ({len(flips)})", "", *(flips or ["- none"])]
    L += ["", f"### Publishers graph recommends that formula does not ({len(adds)})", "", *(adds or ["- none"])]
    L += ["", f"### Publishers formula recommends that graph does not ({len(drops)})", "",
          *(drops or ["- none"])]
    return "\n".join(L)


# ---------------------------------------------------------------- tuning sweep

SWEEP = {  # graph.through.term, .persona, edges.audience, audience_min, penalty_below, corroboration, max_hops
    "term": [1.0, 0.7, 0.5], "persona": [0.2, 0.35, 0.5], "audience": [0.4, 0.6],
    "audience_min": [0.6, 0.7], "penalty_below": [0.25, 0.35], "corroboration": [0.25, 0.5],
    "max_hops": [3, 4]}


def _fast_metrics(pre, t) -> tuple[int, int, int, list[list[str]]]:
    """Outcome hits, must-hit count, must-not violations, recommended ids per case (stage-1 logic
    from app.pipeline on precomputed briefs and gate outcomes)."""
    from app.match import is_weak_fit, mark_stretch, score_publishers

    ok = hit = bad = 0
    recs = []
    for c, b, o, catalog in pre:
        rec: list[str] = []
        if o == "proceed":
            s = score_publishers(b, catalog, t)
            weak = is_weak_fit(s, t)
            rec = [p.publisher_id for p in (mark_stretch(s, t) if weak else s) if p.recommended]
            o = "weak_fit" if weak else "proceed"
        ok += o in c["expected"]
        if o in BUILT:
            hit += len(set(c.get("must_publishers", [])) & set(rec))
            bad += len(set(c.get("must_not_publishers", [])) & set(rec))
        recs.append(rec)
    return ok, hit, bad, recs


def sweep() -> str:
    """Pick the graph tuning on TRAIN only: configs that match formula on outcome accuracy and
    must-hit with no must-not, most formula-like recommended sets first. Test is reported after."""
    from app.understand import clamp_brief, understand

    catalog = load_catalog(ROOT / "data")
    llm = CachedProvider(_NoLive(), ROOT / ".cache" / "llm")
    base = tuning_for("formula")
    pre = {}
    for split in ("train", "test"):
        pre[split] = []
        for c in load_cases(split=split):
            text = c["text"].strip()[: base.input.max_chars]
            b = clamp_brief(understand(text, catalog, llm), base)
            pre[split].append((c, b, get_gate("llm", tuning=base).assess(text, b).outcome, catalog))
    form = {sp: _fast_metrics(pre[sp], base) for sp in pre}
    rows = []
    for combo in itertools.product(*SWEEP.values()):
        k = dict(zip(SWEEP, combo))
        t = tuning_for("graph", base)
        t.graph.through = {"term": k["term"], "persona": k["persona"], "publisher": t.graph.through["publisher"]}
        t.graph.edges.audience, t.graph.audience_min = k["audience"], k["audience_min"]
        t.graph.penalty_below, t.graph.corroboration, t.graph.max_hops = (
            k["penalty_below"], k["corroboration"], k["max_hops"])
        row = {"k": k}
        for sp in pre:
            ok, hit, bad, recs = _fast_metrics(pre[sp], t)
            ov = sum(_jaccard(a, b) for a, b in zip(recs, form[sp][3])) / len(recs)
            row[sp] = (ok, hit, bad, ov)
        rows.append(row)

    def ties(r, sp):
        ok, hit, bad, _ = r[sp]
        return ok >= form[sp][0] and hit >= form[sp][1] and bad == 0

    tied = sorted((r for r in rows if ties(r, "train")), key=lambda r: (-r["train"][1], -r["train"][3]))
    both = [r for r in tied if ties(r, "test")]
    L = [f"formula: train {form['train'][0]} correct, {form['train'][1]} must-hits; "
         f"test {form['test'][0]} correct, {form['test'][1]} must-hits",
         f"{len(rows)} graph configs; {len(tied)} tie formula on train; {len(both)} of those also tie on test; "
         f"none beats formula on train must-hit: {not any(r['train'][1] > form['train'][1] for r in rows)}"]
    for term in SWEEP["term"]:
        sub = [r for r in tied if r["k"]["term"] == term]
        L.append(f"  through.term {term}: {len(sub)} tie on train, "
                 f"{sum(r in both for r in sub)} also on test")
    if tied:
        r = tied[0]
        L.append(f"chosen (train): {r['k']} -> train {r['train'][:3]}, overlap {r['train'][3]:.0%}; "
                 f"test {r['test'][:3]}, overlap {r['test'][3]:.0%}")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.compare_graph")
    ap.add_argument("--split", choices=["train", "test", "all"], default="all")
    ap.add_argument("--out", type=Path, default=None, help="also write the markdown report here")
    ap.add_argument("--sweep", action="store_true", help="the train-only tuning sweep")
    a = ap.parse_args(argv)
    if a.sweep:
        print(sweep())
        return 0
    cases = load_cases(split=a.split)
    recs = run_all(cases)
    text = report(recs, load_catalog(ROOT / "data"))
    print(text)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
