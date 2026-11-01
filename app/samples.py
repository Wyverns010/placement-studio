"""Example advertisers from the data pack (the landing page's sample buttons)."""
from __future__ import annotations

import re
from pathlib import Path

LABELS = {
    1: "Senior dog food", 2: "Recycled activewear", 3: "Adaptogen soda", 4: "Vermont candles",
    5: "We help people feel better", 6: "Backcountry shells", 7: "Dental SaaS (B2B)",
    8: "A thing for moms", 9: "Refillable cleaning", 10: "Florence handbags",
    11: "Protein bars", 12: "Cat starter box", 13: "Value supplements", 14: "Linen bedding",
    15: "idk just try it",
}
_LINE = re.compile(r"^(\d+)\.\s+(.*\S)\s*$")
ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "data/example_advertisers.txt"


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
