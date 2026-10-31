"""Laya gate: a calibrated encoder (convaiinnovations/laya, Apache-2.0) answers typed questions.

Install with ``uv sync --group laya``. The checkpoint loads once per process (lazy, thread-safe).
"""
from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

import yaml

from app.catalog import Catalog, load_catalog
from app.gate import decide_outcome
from app.models import Brief, GateResult
from app.tuning import Tuning

MODEL_ID = "convaiinnovations/laya"
SUBFOLDER = "typed-decisions"
QUESTIONS = Path(__file__).resolve().parents[2] / "prompts" / "laya_questions.yaml"
BUYERS = ("consumer", "business", "not_shoppable", "unclear")

_AGENT = None
_LOAD_LOCK = threading.Lock()
_PREDICT_LOCK = threading.Lock()  # one checkpoint, shared across request/eval threads


def _load_agent():
    import laya

    return laya.load(MODEL_ID, subfolder=SUBFOLDER)


def get_agent():
    global _AGENT
    if _AGENT is None:
        with _LOAD_LOCK:
            if _AGENT is None:
                _AGENT = _load_agent()
    return _AGENT


@lru_cache(maxsize=None)
def _load_questions(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_questions(path: Path = QUESTIONS) -> dict:
    return _load_questions(Path(path))


def tag_primaries(catalog: Catalog) -> dict[str, set[str]]:
    """Each vocab tag -> the primary categories of the publishers that carry it."""
    out: dict[str, set[str]] = {}
    for p in catalog.publishers:
        for tag in p.tags:
            out.setdefault(tag, set()).add(p.category)
    return out


class LayaGate:
    def __init__(self, tuning: Tuning, agent=None, catalog: Catalog | None = None):
        self.t = tuning.gate.for_impl("laya")
        self.factor = tuning.gate.category_disagreement_factor
        self.agent = agent if agent is not None else get_agent()
        self.questions = load_questions()
        self._primaries = tag_primaries(catalog or load_catalog())

    def _allowed(self, brief: Brief) -> set[str]:
        tags = [*brief.categories, *brief.adjacent_categories]
        return {c for tag in tags for c in self._primaries.get(tag, ())}

    def assess(self, text: str, brief: Brief) -> GateResult:
        state = {"advertiser_text": text, "brief_categories": list(brief.categories)}
        with _PREDICT_LOCK:
            res = self.agent.predict(state, self.questions)
        a = res["answers"]
        has_content = float(a["has_content"]["noul"])
        buyer = {b: float(a["buyer"]["probabilities"].get(b, 0.0)) for b in BUYERS}
        p_ident = float(a["product_identifiable"]["noul"])
        cat = a["category"]["choice"]
        allowed = self._allowed(brief)
        agrees = cat in allowed or (cat == "other" and not allowed)
        clarity = p_ident * (1.0 if agrees else self.factor)
        signals = {
            "p_has_content": has_content,
            "p_product_identifiable": p_ident,
            "buyer": a["buyer"]["choice"],
            **{f"buyer_{b}": p for b, p in buyer.items()},
            "category": cat,
            "category_prob": float(a["category"].get("probabilities", {}).get(cat, 0.0)),
            "category_agrees": 1.0 if agrees else 0.0,
        }
        return decide_outcome(has_content=has_content,
                              business_prob=buyer["business"] + buyer["not_shoppable"],
                              clarity=clarity, t=self.t, impl="laya", signals=signals)
