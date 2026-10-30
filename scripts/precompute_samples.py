"""Run the 15 example advertisers through the real pipeline and cache the results.

    make samples        # needs OPENAI_API_KEY (from .env or the environment)

Writes cache/samples.json as {normalised_text: CampaignResult}. Re-run whenever prompts or
tuning change. The API replays these instantly, so the demo works without any LLM call.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.catalog import load_catalog  # noqa: E402
from app.gate import get_gate  # noqa: E402
from app.llm import get_provider  # noqa: E402
from app.pipeline import collect, run_pipeline  # noqa: E402
from app.samples import CACHE, load_samples, norm  # noqa: E402
from app.tuning import load_tuning  # noqa: E402

# Spec table "Expected outcomes for the 15 examples"; any listed outcome is acceptable.
EXPECTED: dict[int, tuple[str, ...]] = {
    1: ("proceed",), 2: ("proceed",), 3: ("proceed",), 4: ("proceed",), 5: ("clarify",),
    6: ("weak_fit",), 7: ("out_of_scope",), 8: ("clarify",), 9: ("proceed", "weak_fit"),
    10: ("weak_fit",), 11: ("proceed",), 12: ("proceed",), 13: ("proceed",), 14: ("proceed",),
    15: ("no_signal",),
}


def main() -> int:
    t, catalog, llm, gate = load_tuning(), load_catalog(), get_provider(), get_gate(tuning=load_tuning())
    budget = t.budget.default_monthly_usd
    samples = load_samples()

    def run(s: dict):
        text = s["text"][: t.input.max_chars]  # same truncation as the API
        return collect(run_pipeline(text, budget, llm=llm, gate=gate, catalog=catalog, t=t))

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(run, samples))

    out = {norm(r.input_text): r.model_dump(mode="json") for r in results}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                     encoding="utf-8")

    bad = 0
    print(f"wrote {len(out)} entries to {CACHE}")
    for s, r in zip(samples, results):
        want = EXPECTED.get(s["id"], ())
        ok = r.outcome in want
        bad += not ok
        print(f"{'✓' if ok else '✗'} {s['id']:>2} {s['label']:<28} got={r.outcome:<13} "
              f"expected={'|'.join(want)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
