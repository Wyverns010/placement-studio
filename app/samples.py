"""Example advertisers (from the data pack) and the precomputed stage results for them."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel

from app.models import CampaignConfig, CampaignResult, Creative, PersonaScore, PublisherScore

log = logging.getLogger(__name__)

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


CACHE_FORMAT = 2  # cache/samples.json: {"format": 2, "fingerprint": sha256, "samples": {normalised_text: SampleEntry}}


def _fingerprint_files(root: Path) -> list[Path]:
    """What a cached result depends on: tuning, every prompt file, and the catalog JSON.
    prompts/README.md is documentation (never sent to a model), so it is left out."""
    prompts = [p for p in (root / "prompts").rglob("*")
               if p.is_file() and not p.name.startswith(".") and p.name != "README.md"
               and "__pycache__" not in p.parts]
    return sorted([root / "config/tuning.yaml", *prompts, *(root / "data").glob("*.json")],
                  key=lambda p: p.relative_to(root).as_posix())


def fingerprint(root: Path = ROOT) -> str:
    """sha256 over (relative path, bytes) of every input the cached samples were built from."""
    h = hashlib.sha256()
    for p in _fingerprint_files(Path(root)):
        h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


_memo: dict[tuple[Path, int, int], dict[str, SampleEntry]] = {}


def _entries(raw) -> dict[str, SampleEntry]:
    """The valid entries of a parsed cache file of this format (invalid ones are skipped)."""
    out: dict[str, SampleEntry] = {}
    if isinstance(raw, dict) and raw.get("format") == CACHE_FORMAT:
        for item in (raw.get("samples") or {}).values():
            try:
                e = SampleEntry.model_validate(item)
            except ValueError:
                continue
            out.setdefault(norm(e.stage1.input_text), e)
    return out


def read_entries(path: Path | None = None) -> dict[str, SampleEntry]:
    """Every entry in the cache file, whatever its fingerprint (for offline checks)."""
    return _entries(json.loads(Path(path or CACHE).read_text(encoding="utf-8")))


def _load_cache(path: Path) -> dict[str, SampleEntry]:
    """Parse the cache file once per (path, mtime, size); {} when missing, unreadable, another
    format, or stale (its fingerprint is not the current inputs': one log line, samples run live)."""
    try:
        st = path.stat()
        key = (path, st.st_mtime_ns, st.st_size)
        if key in _memo:
            return _memo[key]
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = _entries(raw)
    if out and raw.get("fingerprint") != fingerprint():
        log.warning("sample cache %s is stale (tuning, prompts or data changed since it was built); "
                    "samples run live until `make samples`", path)
        out = {}
    _memo.clear()
    _memo[key] = out
    return out


def write_cache(entries: list[SampleEntry], path: Path | None = None) -> None:
    path = Path(path or CACHE)
    data = {"format": CACHE_FORMAT, "fingerprint": fingerprint(),
            "samples": {norm(e.stage1.input_text): e.model_dump(mode="json", exclude={"stage1": {"stage_token"}})
                        for e in entries}}
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


# ---- offline checks: does a cached entry still match the code? (no LLM calls) ----

class _ReplayLLM:
    """Answers stage 1's LLM calls from a cached entry: its brief and its clarify questions."""

    def __init__(self, stage1: CampaignResult):
        self.stage1 = stage1

    def parse(self, *, system: str, user: str, schema, model: str):
        from app.create import ClarifyBatch
        from app.llm import LLMError

        if schema is ClarifyBatch:
            return ClarifyBatch(questions=self.stage1.clarify)
        if self.stage1.brief is not None and schema.__name__ == "BriefSchema":
            return schema.model_validate(self.stage1.brief.model_dump())
        raise LLMError(f"no cached answer for {schema.__name__}")


def replay_stage1(entry: SampleEntry, *, catalog, t) -> CampaignResult:
    """Stage 1 re-run from the cached brief (and clarify questions) through the current gate,
    match and persona code."""
    from app.gate import get_gate
    from app.pipeline import collect, run_stage1

    s1 = entry.stage1
    impl = s1.gate.impl if s1.gate else "llm"
    return collect(run_stage1(s1.input_text, s1.budget_usd, llm=_ReplayLLM(s1),
                              gate=get_gate(impl, tuning=t), catalog=catalog, t=t))


def rebuild_config(entry: SampleEntry, *, catalog, t) -> CampaignConfig | None:
    """Stage 3 (code only) at the recommended budget from the cached stage 1 and creatives."""
    from app.pipeline import BUILT, make_config

    s1 = entry.stage1
    if s1.outcome not in BUILT or not entry.creatives:
        return None
    return make_config(s1.brief, s1.gate, s1.publishers, s1.personas, entry.creatives, None,
                       catalog=catalog, t=t)
