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
    aov_below_log2_scale: float
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


class AffinityScores(BaseModel):
    direct: float
    adjacent: float


class PersonaTuning(BaseModel):
    weights: PersonaWeights
    affinity_scores: AffinityScores
    price_ideal: dict[str, float]
    price_scale: float
    conflict_penalty: float
    cutoff: float
    min: int
    max: int


class BudgetTuning(BaseModel):
    min_usd: float
    max_usd: float
    assumed_cpm_usd: float
    min_share: float
    weak_fit_test_fraction: float
    conversions_per_line_item: int
    round_to_usd: float


class FrequencyCap(BaseModel):
    impressions: int
    per_days: int


class BidTuning(BaseModel):
    cpa_fraction_of_order_value: float
    subscription_ltv_multiplier: float
    guardrail_cpa_multiple: float
    guardrail_min_impressions: int


class FrequencyTuning(BaseModel):
    by_price_tier: dict[str, FrequencyCap]
    subscription_extra: int
    weak_fit_reduction: int
    min_impressions: int


class LayaThresholds(BaseModel):
    """Thresholds fit for the Laya gate (its probabilities live on a different scale)."""

    proceed_threshold: float
    no_signal_threshold: float
    business_threshold: float


class GateTuning(BaseModel):
    proceed_threshold: float
    no_signal_threshold: float
    business_threshold: float
    category_disagreement_factor: float
    laya: LayaThresholds | None = None  # absent -> the Laya gate uses the values above

    def for_impl(self, impl: str) -> GateTuning:
        """The thresholds a gate implementation reads: gate.laya overrides for Laya when set."""
        return self.model_copy(update=self.laya.model_dump()) if impl == "laya" and self.laya else self


class CreativeTuning(BaseModel):
    headline_max_chars: int
    body_max_chars: int
    cta_max_chars: int
    claim_words: list[str]
    banned_phrases: list[str]
    note_max_chars: int
    age_range_bounds: tuple[int, int]
    audience_words: list[str]
    headline_similarity: float


class InputTuning(BaseModel):
    max_chars: int


class AudienceTuning(BaseModel):
    age_floor: int
    age_ceiling: int


class RateLimitTuning(BaseModel):
    per_client_runs: int
    per_client_window_s: float
    global_runs_per_hour: int
    cost_stage1: int
    cost_creatives: int
    cost_regenerate: int


class Tuning(BaseModel):
    publisher: PublisherTuning
    persona: PersonaTuning
    budget: BudgetTuning
    bid: BidTuning
    frequency: FrequencyTuning
    gate: GateTuning
    creative: CreativeTuning
    input: InputTuning
    audience: AudienceTuning
    ratelimit: RateLimitTuning


def load_tuning(path: Path = Path("config/tuning.yaml")) -> Tuning:
    return Tuning(**yaml.safe_load(Path(path).read_text()))
