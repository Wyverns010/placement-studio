"""Run the 15 example advertisers through all three stages and cache each stage's result.

    make samples        # needs OPENAI_API_KEY (from .env or the environment)

Writes cache/samples.json as {"format": 2, "samples": {normalised_text: {stage1, creatives,
config}}}: the stage-1 result (no creatives or config), the creatives, and the config at the
recommended budget. Re-run whenever prompts or tuning change. The API serves stage 1 and the
creatives from here instantly, so the default click-through needs no LLM call.
"""
from __future__ import annotations

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
from app.pipeline import run_full  # noqa: E402
from app.samples import CACHE, SampleEntry, load_samples, write_cache  # noqa: E402
from app.tuning import load_tuning  # noqa: E402

# The expected outcomes for the 15 given examples; any listed outcome is acceptable.
EXPECTED: dict[int, tuple[str, ...]] = {
    1: ("proceed",), 2: ("proceed",), 3: ("proceed",), 4: ("proceed",), 5: ("clarify",),
    6: ("weak_fit",), 7: ("out_of_scope",), 8: ("clarify",), 9: ("proceed", "weak_fit"),
    10: ("weak_fit",), 11: ("proceed",), 12: ("proceed",), 13: ("proceed",), 14: ("proceed",),
    15: ("no_signal",),
}


def main() -> int:
    t, catalog, llm, gate = load_tuning(), load_catalog(), get_provider(), get_gate(tuning=load_tuning())
    samples = load_samples()

    def run(s: dict):
        text = s["text"][: t.input.max_chars]  # same truncation as the API
        return run_full(text, None, llm=llm, gate=gate, catalog=catalog, t=t)  # recommended budget

    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(run, samples))

    entries = [SampleEntry(stage1=r.model_copy(update={"creatives": [], "config": None}),
                           creatives=r.creatives, config=r.config) for r in results]
    write_cache(entries)

    bad = 0
    print(f"wrote {len(entries)} entries to {CACHE}")
    for s, r in zip(samples, results):
        want = EXPECTED.get(s["id"], ())
        ok = r.outcome in want
        bad += not ok
        print(f"{'✓' if ok else '✗'} {s['id']:>2} {s['label']:<28} got={r.outcome:<13} "
              f"expected={'|'.join(want)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
