from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class PublisherWeights(BaseModel):
    category: float
    audience: float
    income: float
    aov: float


class CategoryScores(BaseModel):
    primary: float
    subcategory: float
    same_category: float
    adjacent: float
    attribute: float


class AudienceWeights(BaseModel):
    age: float
    gender: float


class PublisherTuning(BaseModel):
    weights: PublisherWeights
    category_scores: CategoryScores
    attribute_tags: list[str]
    audience_weights: AudienceWeights
    income_targets: dict[str, float]
    income_scale: float
    aov_log2_scale: float
    no_category_penalty: float
    aov_gate_floor: float
    unknown_factor: float
    cutoff: float
    max_recommended: int
    weak_fit_min_recommended: int
    weak_fit_show: int


class PersonaWeights(BaseModel):
    affinity: float
    price: float
    age: float


class PersonaTuning(BaseModel):
    weights: PersonaWeights
    conflict_penalty: float
    cutoff: float
    min: int
    max: int


class BudgetTuning(BaseModel):
    default_monthly_usd: float
    min_usd: float
    max_usd: float
    assumed_cpm_usd: float
    min_share: float
    weak_fit_test_fraction: float


class FrequencyCap(BaseModel):
    impressions: int
    per_days: int


class BidTuning(BaseModel):
    cpa_fraction_of_order_value: float
    subscription_ltv_multiplier: float
    frequency_cap: FrequencyCap
    guardrail_cpa_multiple: float
    guardrail_min_impressions: int


class GateTuning(BaseModel):
    proceed_threshold: float
    no_signal_threshold: float
    business_threshold: float
    category_disagreement_factor: float


class CreativeTuning(BaseModel):
    headline_max_chars: int
    body_max_chars: int
    cta_max_chars: int


class InputTuning(BaseModel):
    max_chars: int


class Tuning(BaseModel):
    publisher: PublisherTuning
    persona: PersonaTuning
    budget: BudgetTuning
    bid: BidTuning
    gate: GateTuning
    creative: CreativeTuning
    input: InputTuning


def load_tuning(path: Path = Path("config/tuning.yaml")) -> Tuning:
    return Tuning(**yaml.safe_load(Path(path).read_text()))
