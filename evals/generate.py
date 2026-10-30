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
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from app.catalog import load_catalog
from app.llm import get_provider, model_fast
from app.prompts import render
from evals.run import split_for

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "evals" / "candidates.jsonl"
GIVEN = ROOT / "data" / "example_advertisers.txt"
BUCKETS: dict[str, str] = yaml.safe_load((ROOT / "prompts" / "eval_buckets.yaml").read_text())


class Candidate(BaseModel):
    text: str
    expected: Literal["proceed", "weak_fit", "clarify", "out_of_scope", "no_signal"]
    rationale: str


class CandidateBatch(BaseModel):
    items: list[Candidate]


def _given() -> list[str]:
    lines = GIVEN.read_text().splitlines()
    return [ln.split(". ", 1)[1] for ln in lines if ln[:1].isdigit() and ". " in ln]


def build_prompt(bucket: str, n: int, hint: str) -> tuple[str, str]:
    """(system, user) for one drafting call, rendered from prompts/eval_candidates*.md."""
    cat = load_catalog(ROOT / "data")
    pubs = "\n".join(f"- {p.id} {p.name}: {p.category} ({', '.join(p.subcategories)}), "
                     f"AOV ${p.avg_order_value_usd:.0f}" for p in cat.publishers)
    given = ""
    if bucket == "paraphrase":
        given = "\n\n# Given examples\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(_given(), 1))
    system = render("eval_candidates", publishers=pubs, given=given, n=n,
                    bucket_desc=BUCKETS[bucket], hint=f" Focus: {hint}." if hint else "")
    return system, render("eval_candidates_user").strip()


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(prog="evals.generate")
    ap.add_argument("--bucket", choices=sorted(BUCKETS), required=True)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--hint", default="")
    ap.add_argument("--out", type=Path, default=CANDIDATES)
    a = ap.parse_args(argv)
    os.environ.setdefault("LLM_CACHE_DIR", str(ROOT / ".cache" / "llm"))

    system, user = build_prompt(a.bucket, a.n, a.hint)
    out = get_provider().parse(system=system, user=user, schema=CandidateBatch, model=model_fast())
    stamp = _run_stamp()  # ids stay unique across runs appended to the same file
    with a.out.open("a") as f:
        for i, c in enumerate(out.items, 1):
            group = f"gen-{a.bucket}-{stamp}-{i:02d}"
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
