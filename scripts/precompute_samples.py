"""Run the 15 example advertisers through all three stages and cache each stage's result.

    make samples                                       # live: needs OPENAI_API_KEY (.env or env)
    uv run python scripts/precompute_samples.py --offline   # no LLM: re-check and re-stamp

Writes cache/samples.json as {"format": 2, "fingerprint": sha256, "samples": {normalised_text:
{stage1, creatives, config, mode, agent_trace, agent_notes}}}: the stage-1 result (no creatives
or config), the creatives written by the step agents (Copywriter + Critic, via the same
creatives_step as /api/creatives) with their trace and notes, and the config at the recommended
budget. If the agents fall back on any sample the run exits 1 and writes nothing. The fingerprint covers config/tuning.yaml, prompts/ and
data/*.json (app.samples.fingerprint); the API ignores a cache whose fingerprint no longer matches
and runs the samples live. Re-run whenever prompts or tuning change.

--offline makes no LLM call: it re-scores every cached brief through the current gate, match and
persona code, refuses (exit 1) if any stage-1 result differs, otherwise rebuilds each config
(stage 3 is code only) and re-stamps the fingerprint. Use it after a code-only change.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.catalog import load_catalog  # noqa: E402
from app.samples import (CACHE, SampleEntry, load_samples, read_entries, rebuild_config,  # noqa: E402
                         replay_stage1, write_cache)
from app.tuning import load_tuning  # noqa: E402

# The expected outcomes for the 15 given examples; any listed outcome is acceptable.
EXPECTED: dict[int, tuple[str, ...]] = {
    1: ("proceed",), 2: ("proceed",), 3: ("proceed",), 4: ("proceed",), 5: ("clarify",),
    6: ("weak_fit",), 7: ("out_of_scope",), 8: ("clarify",), 9: ("proceed", "weak_fit"),
    10: ("weak_fit",), 11: ("proceed",), 12: ("proceed",), 13: ("proceed",), 14: ("proceed",),
    15: ("no_signal",),
}


class AgentFellBack(RuntimeError):
    """Step ② did not come from the agents (fell back, or agents are off): never cache code ads."""


def build_entry(text: str, *, llm, gate, catalog, t, runtime) -> SampleEntry:
    """One sample through all three stages. Stage 1 is the code path (strategist unsteered =
    code); step ② runs through creatives_step, the code /api/creatives uses, and must be the
    agents' result (AgentFellBack otherwise); stage 3 is code at the recommended budget."""
    from app.pipeline import BUILT, collect, make_config, run_stage1
    from app.stepagents.runtime import wants_agent
    from app.stepagents.steps import creatives_step

    r = collect(run_stage1(text, None, llm=llm, gate=gate, catalog=catalog, t=t))
    if r.outcome not in BUILT:
        return SampleEntry(stage1=r)
    if runtime is None or not wants_agent("creative", None, t):
        raise AgentFellBack("step-agent runtime is off (no OPENAI_API_KEY, agents.enabled false, "
                            "or agents.run_without_steer.creative false)")
    creatives, meta = creatives_step(text, r.brief, r.publishers, r.personas, None, llm=llm,
                                     catalog=catalog, t=t, runtime=runtime)
    if meta["mode"] != "agent" or not creatives:
        notes = "; ".join(meta.get("agent_notes", []))
        raise AgentFellBack(f"creative agents returned mode={meta['mode']!r}: {notes}")
    config = make_config(r.brief, r.gate, r.publishers, r.personas, creatives, None,
                         catalog=catalog, t=t)
    return SampleEntry(stage1=r, creatives=creatives, config=config, mode="agent",
                       agent_trace=meta["agent_trace"], agent_notes=meta["agent_notes"])


def live() -> list[SampleEntry]:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from app.gate import get_gate
    from app.llm import get_provider
    from app.stepagents.runtime import openai_runtime

    t, catalog, llm = load_tuning(), load_catalog(), get_provider()
    gate = get_gate(tuning=t)

    runtime = openai_runtime(t)

    def run(s: dict):
        text = s["text"][: t.input.max_chars]  # same truncation as the API
        return build_entry(text, llm=llm, gate=gate, catalog=catalog, t=t, runtime=runtime)

    with ThreadPoolExecutor(max_workers=5) as ex:
        return list(ex.map(run, load_samples()))  # any AgentFellBack propagates: nothing is written


def offline() -> list[SampleEntry] | None:
    t, catalog = load_tuning(), load_catalog()
    out, stale = [], 0
    skip = {"stage_token", "budget_usd"}
    for e in read_entries(CACHE).values():
        if replay_stage1(e, catalog=catalog, t=t).model_dump(exclude=skip) != e.stage1.model_dump(exclude=skip):
            stale += 1
            print(f"✗ stage 1 no longer reproduces: {e.stage1.input_text[:60]!r}")
        out.append(e.model_copy(update={"config": rebuild_config(e, catalog=catalog, t=t)}))
    if stale:
        print(f"{stale} cached stage-1 result(s) changed under current code: run `make samples`")
        return None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="no LLM: verify stage 1, rebuild configs, re-stamp")
    args = ap.parse_args()
    try:
        entries = offline() if args.offline else live()
    except AgentFellBack as e:
        print(f"✗ precompute failed, cache not written: {e}")
        return 1
    if entries is None:
        return 1
    write_cache(entries)
    print(f"wrote {len(entries)} entries to {CACHE}")
    bad = 0
    by_text = {" ".join(e.stage1.input_text.split()): e for e in entries}
    for s in load_samples():
        e = by_text.get(" ".join(s["text"].split()))
        got = e.stage1.outcome if e else "missing"
        want = EXPECTED.get(s["id"], ())
        ok = got in want
        bad += not ok
        print(f"{'✓' if ok else '✗'} {s['id']:>2} {s['label']:<28} got={got:<13} "
              f"expected={'|'.join(want)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
