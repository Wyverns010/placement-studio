from __future__ import annotations

from pydantic import BaseModel, Field


class PublisherTuning(BaseModel):
    weights: dict[str, float]  # category, audience, income, aov
    category_scores: dict[str, float]  # primary, subcategory, same_category, adjacent, attribute
    attribute_tags: list[str]
    audience_weights: dict[str, float]  # age, gender
    income_targets: dict[str, float]
    income_scale: float
    aov_log2_scale: float
    aov_below_log2_scale: float
    no_category_penalty: float
    affinity_parents: dict[str, str] = {}
    scoped_terms: dict[str, str] = {}
    aov_gate_floor: float
    unknown_factor: float
    cutoff: float
    max_recommended: int
    weak_fit_min_recommended: int
    weak_fit_show: int


class PersonaTuning(BaseModel):
    weights: dict[str, float]  # affinity, price, age, publishers
    affinity_scores: dict[str, float]  # direct, family, adjacent, sibling
    price_ideal: dict[str, float]
    price_scale: float
    conflict_penalty: float
    cutoff: float
    min: int
    max: int
    age_mismatch_penalty: float = 0.0  # the brief states ages and this persona's range misses them
    niche_penalty: float = 0.0  # a one-category shopper (pet owners) with no affinity to this brief
    attribute_affinities: dict[str, list[str]] = {}  # persona id -> brief attribute tags it shops by
    mode_bonus: float = 0.15  # added to affinity (at least family) when the brief names the mode


class BudgetTuning(BaseModel):
    min_usd: float
    max_usd: float
    assumed_cpm_usd: float  # CPM for an income tier missing from cpm_by_income_usd
    cpm_by_income_usd: dict[str, float] = {}  # publisher audience income tier -> CPM
    max_share_of_impressions: float = Field(gt=0, le=1)  # most of a publisher one campaign can buy
    min_share: float
    weak_fit_test_fraction: float
    weak_fit_test_max_usd: float
    learning_conversions_per_week: int  # what a CPA bid needs per line item to leave learning
    weeks_per_month: int
    max_conversions_per_1k_impressions: float  # above this the target CPA is flagged as a stretch
    round_to_usd: float = Field(gt=0)

    @property
    def conversions_per_month(self) -> int:
        return self.learning_conversions_per_week * self.weeks_per_month


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
    weak_fit_max_per_days: int
    min_impressions: int


class GateTuning(BaseModel):
    proceed_threshold: float
    no_signal_threshold: float
    business_threshold: float


class CreativeTuning(BaseModel):
    headline_max_chars: int
    body_max_chars: int
    cta_max_chars: int
    claim_words: list[str]
    banned_phrases: list[str]
    note_max_chars: int
    parrot_ngram: int
    parrot_sentence_min_words: int
    age_range_bounds: tuple[int, int]
    audience_words: list[str]
    headline_similarity: float


class InputTuning(BaseModel):
    age_floor: int  # fills a missing lower age bound ("under 35" -> 18-35)
    age_ceiling: int  # fills a missing upper age bound ("over 50" -> 50-80)
    max_chars: int
    max_answers: int
    max_answer_chars: int
    max_body_bytes: int
    brief_product_max_chars: int
    brief_list_max_items: int
    brief_item_max_chars: int
    brief_categories_max: int
    brief_age_max: int
    buyer_age_min: int = 18


class ClarifyTuning(BaseModel):
    max_questions: int
    max_options: int
    min_options: int


class Stage1Tuning(BaseModel):
    top_publishers_shown: int
    clarify_publishers_shown: int


class LLMTuning(BaseModel):
    timeout_s: float


class RateLimitTuning(BaseModel):
    per_client_runs: int
    per_client_window_s: float
    global_runs_per_hour: int
    cost_stage1: int
    cost_creatives: int
    cost_regenerate: int


class AgentPrice(BaseModel):
    input: float
    cached_input: float
    output: float


class AgentsTuning(BaseModel):
    enabled: bool
    run_without_steer: dict[str, bool]  # strategist | creative | media_planner
    steer_max_chars: int
    max_turns: dict[str, int]  # strategist | copywriter | critic | media_planner
    min_recommended_after_steer: int  # a steer never shrinks the recommended set below min(this, n)
    max_share_after_steer: float  # most budget one publisher may get after a planner exclusion
    critic_max_rounds: int
    critic_stop_fraction: float  # share of the step's cap after which critic reviews are refused
    creative_est_usd_per_ad: float  # projected agent cost per ad (checked before spending)
    max_cost_usd: dict[str, float]  # strategist | creative | media_planner
    timeout_s: float  # per model call
    max_retries: int  # per model call
    step_timeout_s: float  # whole step run
    max_notes: int
    note_max_chars: int
    trace_args_chars: int
    trace_result_chars: int
    ratelimit_cost_config: int
    prices_per_1m_usd: dict[str, AgentPrice]  # model name -> price; "default" for any other


class Tuning(BaseModel):
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
    stage1: Stage1Tuning
    llm: LLMTuning
    agents: AgentsTuning

