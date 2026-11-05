from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a key the code doesn't read is an error, not dead config


class PublisherTuning(Strict):
    weights: dict[str, float]  # category, audience, income, aov
    category_scores: dict[str, float]  # primary, subcategory, same_category, adjacent, attribute
    attribute_tags: list[str]
    audience_weights: dict[str, float]  # age, gender
    income_targets: dict[str, float]
    income_scale: float
    aov_log2_scale: float
    aov_below_log2_scale: float
    no_category_penalty: float
    affinity_parents: dict[str, str]
    scoped_terms: dict[str, str]
    aov_gate_floor: float
    unknown_factor: float
    cutoff: float
    max_recommended: int
    weak_fit_min_recommended: int
    weak_fit_show: int


class PersonaTuning(Strict):
    weights: dict[str, float]  # affinity, price, age, publishers
    affinity_scores: dict[str, float]  # direct, family, adjacent, sibling
    price_ideal: dict[str, float]
    price_scale: float
    conflict_penalty: float
    cutoff: float
    min: int
    max: int
    age_mismatch_penalty: float  # the brief states ages and this persona's range misses them
    niche_penalty: float  # a one-category shopper (pet owners) with no affinity to this brief
    attribute_affinities: dict[str, list[str]]  # persona id -> brief attribute tags it shops by
    mode_bonus: float  # added to affinity (at least family) when the brief names the mode


class BudgetTuning(Strict):
    min_usd: float
    max_usd: float
    assumed_cpm_usd: float  # CPM for an income tier missing from cpm_by_income_usd
    cpm_by_income_usd: dict[str, float]  # publisher audience income tier -> CPM
    max_share_of_impressions: float = Field(gt=0, le=1)  # most of a publisher one campaign can buy
    min_share: float
    weak_fit_test_fraction: float
    weak_fit_test_max_usd: float
    learning_conversions_per_week: int  # what a CPA bid needs per line item to leave learning
    weeks_per_month: int
    max_conversions_per_1k_impressions: float  # above this the target CPA is flagged as a stretch
    round_to_usd: float = Field(gt=0)


class FrequencyCap(Strict):
    impressions: int
    per_days: int


class BidTuning(Strict):
    cpa_fraction_of_order_value: float
    subscription_ltv_multiplier: float
    guardrail_cpa_multiple: float
    guardrail_min_impressions: int


class FrequencyTuning(Strict):
    by_price_tier: dict[str, FrequencyCap]
    subscription_extra: int
    weak_fit_reduction: int
    weak_fit_max_per_days: int
    min_impressions: int


class GateTuning(Strict):
    proceed_threshold: float
    no_signal_threshold: float
    business_threshold: float


class CreativeTuning(Strict):
    headline_max_chars: int
    body_max_chars: int
    cta_max_chars: int
    claim_words: list[str]  # never in an ad unless the advertiser wrote them
    banned_phrases: list[str]  # filler the playbook tells the writer and Critic to avoid
    headline_similarity: float  # word overlap at or above this counts as a duplicate headline


class InputTuning(Strict):
    age_floor: int  # fills a missing lower age bound ("under 35" -> 18-35)
    age_ceiling: int  # fills a missing upper age bound ("over 50" -> 50-80)
    brief_age_max: int  # ages above this in a brief are clamped
    buyer_age_min: int  # ages below this are the product's user, not the buyer


class ClarifyTuning(Strict):
    max_questions: int
    max_options: int
    min_options: int


class RateLimitTuning(Strict):
    per_client_runs: int  # paid runs per client per window
    per_client_window_s: float
    global_runs_per_hour: int  # process-wide cap on paid runs
    cost_campaign: int  # step 1
    cost_ads: int  # step 3: up to 3 calls per persona
    cost_config_note: int  # step 4 with a note (without one it's free)


class Tuning(Strict):
    llm_timeout_s: float  # OpenAI client timeout per request (no SDK retries)
    publisher: PublisherTuning
    persona: PersonaTuning
    budget: BudgetTuning
    bid: BidTuning
    frequency: FrequencyTuning
    gate: GateTuning
    creative: CreativeTuning
    input: InputTuning
    ratelimit: RateLimitTuning
    clarify: ClarifyTuning

