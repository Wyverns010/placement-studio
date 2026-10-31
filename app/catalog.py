from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

INCOME_RANK = {"mid": 1, "mid-high": 2, "high": 3}
PRICE_RANK = {"low": 0.0, "low-medium": 0.5, "medium": 1.0, "medium-high": 1.5, "high": 2.0}


def _ages(s: str) -> tuple[int, int]:
    lo, hi = s.split("-")
    return int(lo), int(hi)


class Audience(BaseModel):
    age_skew: str
    gender_split: dict[str, float]
    top_geos: list[str]
    income_tier: str


class Publisher(BaseModel):
    id: str
    name: str
    category: str
    subcategories: list[str]
    monthly_impressions: int
    avg_order_value_usd: float
    audience: Audience
    notes: str = ""
    age_min: int
    age_max: int
    income_rank: int
    tags: set[str]

    @classmethod
    def from_raw(cls, raw: dict) -> "Publisher":
        lo, hi = _ages(raw["audience"]["age_skew"])
        return cls(
            **raw,
            age_min=lo,
            age_max=hi,
            income_rank=INCOME_RANK[raw["audience"]["income_tier"]],
            tags={raw["category"], *raw["subcategories"]},
        )


class Persona(BaseModel):
    id: str
    name: str
    age_range: str
    gender_skew: str
    description: str
    category_affinities: list[str]
    price_sensitivity: str
    messaging_preferences: list[str]
    disinterested_in: list[str]
    typical_aov_usd: float
    age_min: int
    age_max: int
    price_rank: float

    @classmethod
    def from_raw(cls, raw: dict) -> "Persona":
        lo, hi = _ages(raw["age_range"])
        return cls(
            **raw,
            age_min=lo,
            age_max=hi,
            price_rank=PRICE_RANK[raw["price_sensitivity"]],
        )


class Catalog(BaseModel):
    publishers: list[Publisher]
    personas: list[Persona]

    @property
    def vocab(self) -> list[str]:
        v: set[str] = set()
        for p in self.publishers:
            v |= p.tags
        for q in self.personas:
            v |= set(q.category_affinities)
        return sorted(v)

    def vocab_groups(self) -> dict[str, list[str]]:
        """Publisher category -> the subcategories its publishers carry (sorted, by category)."""
        groups: dict[str, set[str]] = {}
        for p in self.publishers:
            groups.setdefault(p.category, set()).update(p.subcategories)
        return {c: sorted(groups[c]) for c in sorted(groups)}

    def interest_terms(self) -> list[str]:
        """Persona affinity terms that are not a publisher category or subcategory."""
        groups = self.vocab_groups()
        known = set(groups) | {t for ts in groups.values() for t in ts}
        return sorted({a for q in self.personas for a in q.category_affinities} - known)

    @property
    def conflict_vocab(self) -> list[str]:
        return sorted({d for q in self.personas for d in q.disinterested_in})

    def publisher(self, pid: str) -> Publisher:
        for p in self.publishers:
            if p.id == pid:
                return p
        raise KeyError(pid)


@lru_cache(maxsize=None)
def load_catalog(data_dir: Path = Path("data")) -> Catalog:
    pubs = json.loads((data_dir / "publishers.json").read_text())
    pers = json.loads((data_dir / "shopper_personas.json").read_text())
    return Catalog(
        publishers=[Publisher.from_raw(p) for p in pubs],
        personas=[Persona.from_raw(p) for p in pers],
    )
