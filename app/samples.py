"""Example advertisers (from the data pack) and the precomputed-result cache."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.models import CampaignResult
from app.tuning import load_tuning

LABELS = {
    1: "Senior dog food", 2: "Recycled activewear", 3: "Adaptogen soda", 4: "Vermont candles",
    5: "We help people feel better", 6: "Backcountry shells", 7: "Dental SaaS (B2B)",
    8: "A thing for moms", 9: "Refillable cleaning", 10: "Florence handbags",
    11: "Protein bars", 12: "Cat starter box", 13: "Value supplements", 14: "Linen bedding",
    15: "idk just try it",
}
_LINE = re.compile(r"^(\d+)\.\s+(.*\S)\s*$")
EXAMPLES = Path("data/example_advertisers.txt")
CACHE = Path("cache/samples.json")


def norm(text: str) -> str:
    return " ".join(text.split())


def load_samples(path: Path = EXAMPLES) -> list[dict]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line)
        if m:
            n = int(m.group(1))
            out.append({"id": n, "label": LABELS.get(n, f"Example {n}"), "text": m.group(2)})
    return out


def cached_result(text: str, budget: float, *, default_budget: float | None = None,
                  path: Path = CACHE) -> CampaignResult | None:
    """Precomputed result for a sample, only at the default budget."""
    if default_budget is None:
        default_budget = load_tuning().budget.default_monthly_usd
    if budget != default_budget:
        return None
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    items = raw.values() if isinstance(raw, dict) else raw
    key = norm(text)
    for item in items:
        try:
            r = CampaignResult.model_validate(item)
        except ValueError:
            continue
        if norm(r.input_text) == key and r.budget_usd == default_budget:
            return r
    return None
