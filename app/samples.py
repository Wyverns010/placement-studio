"""Example advertisers (from the data pack) and the precomputed stage results for them."""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from app.models import CampaignConfig, CampaignResult, Creative, PersonaScore, PublisherScore

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
CACHE = ROOT / "cache/samples.json"


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


class SampleEntry(BaseModel):
    """One precomputed sample: the stage-1 result, its creatives and the config at the
    recommended budget (empty / None for outcomes that build no campaign)."""
    stage1: CampaignResult
    creatives: list[Creative] = []
    config: CampaignConfig | None = None


CACHE_FORMAT = 2  # cache/samples.json: {"format": 2, "samples": {normalised_text: SampleEntry}}

_memo: dict[tuple[Path, int, int], dict[str, SampleEntry]] = {}


def _load_cache(path: Path) -> dict[str, SampleEntry]:
    """Parse the cache file once per (path, mtime, size); {} when missing, unreadable or another
    format. Invalid entries are skipped."""
    try:
        st = path.stat()
        key = (path, st.st_mtime_ns, st.st_size)
        if key in _memo:
            return _memo[key]
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, SampleEntry] = {}
    if isinstance(raw, dict) and raw.get("format") == CACHE_FORMAT:
        for item in (raw.get("samples") or {}).values():
            try:
                e = SampleEntry.model_validate(item)
            except ValueError:
                continue
            out.setdefault(norm(e.stage1.input_text), e)
    _memo.clear()
    _memo[key] = out
    return out


def write_cache(entries: list[SampleEntry], path: Path | None = None) -> None:
    path = Path(path or CACHE)
    data = {"format": CACHE_FORMAT,
            "samples": {norm(e.stage1.input_text): e.model_dump(mode="json") for e in entries}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def cached_entry(text: str, *, path: Path | None = None) -> SampleEntry | None:
    """The precomputed entry for a sample text (whitespace-insensitive); `path` defaults to CACHE."""
    return _load_cache(Path(path or CACHE)).get(norm(text))


def cached_stage1(text: str, budget_usd: float | None = None, *,
                  path: Path | None = None) -> CampaignResult | None:
    """The precomputed stage-1 result for a sample (any budget: stage 1 doesn't use it; the
    requested budget is echoed like a live run)."""
    e = cached_entry(text, path=path)
    return e.stage1.model_copy(update={"budget_usd": budget_usd}) if e else None


def cached_creatives(text: str, publishers: list[PublisherScore], personas: list[PersonaScore],
                     *, path: Path | None = None) -> list[Creative] | None:
    """Precomputed creatives, only when the request asks for exactly the sample's stage-1 picks
    (same personas in order, same recommended publishers)."""
    e = cached_entry(text, path=path)
    if not e or not e.creatives:
        return None
    rec = lambda ps: [p.publisher_id for p in ps if p.recommended]  # noqa: E731
    if ([p.persona_id for p in personas] != [p.persona_id for p in e.stage1.personas]
            or rec(publishers) != rec(e.stage1.publishers)):
        return None
    return [c.model_copy() for c in e.creatives]
