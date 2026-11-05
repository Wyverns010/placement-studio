from __future__ import annotations

from pydantic import BaseModel

from app.constants.catalog import INCOME_RANK, PRICE_RANK


class Audience(BaseModel):
    age_skew: str
    gender_split: dict[str, float]
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
    def from_raw(cls, raw: dict) -> Publisher:
        low, high = raw["audience"]["age_skew"].split("-")
        return cls(**raw, age_min=int(low), age_max=int(high),
                   income_rank=INCOME_RANK[raw["audience"]["income_tier"]],
                   tags={raw["category"], *raw["subcategories"]})


class Persona(BaseModel):
    id: str
    name: str
    description: str
    category_affinities: list[str]
    price_sensitivity: str
    messaging_preferences: list[str]
    disinterested_in: list[str]
    age_min: int
    age_max: int
    price_rank: float

    @classmethod
    def from_raw(cls, raw: dict) -> Persona:
        low, high = raw["age_range"].split("-")
        return cls(**raw, age_min=int(low), age_max=int(high),
                   price_rank=PRICE_RANK[raw["price_sensitivity"]])


class Catalog(BaseModel):
    publishers: list[Publisher]
    personas: list[Persona]
    publisher_by_id: dict[str, Publisher]
    persona_by_id: dict[str, Persona]
    vocab: list[str]  # every category word: publisher categories, subcategories, persona affinities
    vocab_groups: dict[str, list[str]]  # publisher category -> the subcategories its publishers carry
    interest_terms: list[str]  # persona affinity words that are no publisher category or subcategory
    conflict_vocab: list[str]  # what personas are disinterested in

    @classmethod
    def build(cls, publishers: list[Publisher], personas: list[Persona]) -> Catalog:
        groups: dict[str, set[str]] = {}
        for publisher in publishers:
            groups.setdefault(publisher.category, set()).update(publisher.subcategories)
        affinities = {word for persona in personas for word in persona.category_affinities}
        publisher_words = set(groups) | {word for words in groups.values() for word in words}
        return cls(
            publishers=publishers, personas=personas,
            publisher_by_id={publisher.id: publisher for publisher in publishers},
            persona_by_id={persona.id: persona for persona in personas},
            vocab=sorted({tag for publisher in publishers for tag in publisher.tags} | affinities),
            vocab_groups={category: sorted(groups[category]) for category in sorted(groups)},
            interest_terms=sorted(affinities - publisher_words),
            conflict_vocab=sorted({word for persona in personas for word in persona.disinterested_in}),
        )
