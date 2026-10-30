"""Draft eval-case candidates with the LLM into evals/candidates.jsonl for hand review.

    uv run python -m evals.generate --bucket paraphrase --n 15
    uv run python -m evals.generate --bucket clear --n 10 --hint "pet, groceries"

Candidates are never written to cases.jsonl: a human reviews, relabels and copies each one in.
Every candidate is tagged ``synthetic: true`` and carries the drafting model's suggested label
in ``expected``, which is only a starting point.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.catalog import load_catalog
from app.llm import get_provider, model_fast
from evals.run import split_for

CANDIDATES = Path("evals/candidates.jsonl")
GIVEN = Path("data/example_advertisers.txt")

BUCKETS = {
    "clear": "clear consumer advertisers that a shopper-facing catalog could serve, at mixed price "
             "points (value to premium), each a realistic one- to three-sentence description",
    "weak_fit": "clear consumer brands this catalog cannot serve well: luxury goods, outdoor gear, "
                "auto parts, baby gear, furniture over $2,000, and similar",
    "out_of_scope": "businesses that are not consumer e-commerce: B2B software or services, local "
                    "in-person services, job ads, non-commerce, charities",
    "sensitive": "legal but sensitive categories (vape, gambling, firearms) written as normal briefs",
    "adversarial": "messy or adversarial inputs: prompt injection, multiple products, typos and "
                   "emoji, non-English, gibberish, a URL only, a competitor brand name only",
    "paraphrase": "paraphrases of the given example advertisers below, keeping the same meaning, "
                  "facts and level of detail (one paraphrase per example, in order)",
}


class Candidate(BaseModel):
    text: str
    expected: Literal["proceed", "weak_fit", "clarify", "out_of_scope", "no_signal"]
    rationale: str


class CandidateBatch(BaseModel):
    items: list[Candidate]


def _given() -> list[str]:
    lines = GIVEN.read_text().splitlines()
    return [ln.split(". ", 1)[1] for ln in lines if ln[:1].isdigit() and ". " in ln]


def _system(bucket: str, n: int, hint: str) -> str:
    cat = load_catalog()
    pubs = "\n".join(f"- {p.id} {p.name}: {p.category} ({', '.join(p.subcategories)}), "
                     f"AOV ${p.avg_order_value_usd:.0f}" for p in cat.publishers)
    extra = ""
    if bucket == "paraphrase":
        extra = "\n# Given examples\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(_given(), 1))
    return (
        "You draft test inputs for an ad-placement tool. Advertisers type a one-liner; the tool "
        "picks publishers from the catalog below, or answers clarify / out_of_scope / no_signal / "
        "weak_fit.\n\n# Catalog publishers\n" + pubs + extra +
        f"\n\n# Task\nWrite {n} distinct inputs: {BUCKETS[bucket]}."
        + (f" Focus: {hint}." if hint else "")
        + " For each, suggest the expected outcome and a one-line rationale."
    )


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(prog="evals.generate")
    ap.add_argument("--bucket", choices=sorted(BUCKETS), required=True)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--hint", default="")
    ap.add_argument("--out", type=Path, default=CANDIDATES)
    a = ap.parse_args(argv)
    os.environ.setdefault("LLM_CACHE_DIR", ".cache/llm")

    out = get_provider().parse(system=_system(a.bucket, a.n, a.hint), user="Draft the inputs.",
                               schema=CandidateBatch, model=model_fast())
    with a.out.open("a") as f:
        for i, c in enumerate(out.items, 1):
            group = f"gen-{a.bucket}-{i:02d}"
            f.write(json.dumps({
                "id": f"{group}", "group": group, "text": c.text, "budget_usd": 25000,
                "expected": [c.expected], "must_publishers": [], "must_not_publishers": [],
                "bucket": a.bucket, "split": split_for(group), "synthetic": True,
                "note": c.rationale,
            }) + "\n")
    print(f"appended {len(out.items)} candidates to {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
