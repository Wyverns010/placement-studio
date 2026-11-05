"""Every weight and threshold the steps use, with why. `Tuning()` is the whole set; evals and tests
try other values on a copy (`model_copy(update=...)`).

Pattern: typed settings object. Defaults live in code next to their reason; a variant is an
immutable copy, never a global edit."""
from __future__ import annotations

from pydantic import BaseModel


class PublisherTuning(BaseModel):
    weights: dict[str, float] = {"category": 0.45, "audience": 0.20, "income": 0.15, "aov": 0.20}
    category_scores: dict[str, float] = {"primary": 1.0, "subcategory": 0.85, "same_category": 0.70,
                                         "adjacent": 0.5, "attribute": 0.20}
    audience_weights: dict[str, float] = {"age": 0.7, "gender": 0.3}
    income_targets: dict[str, float] = {"value": 1.0, "mid": 1.5, "premium": 2.5, "luxury": 3.0}  # price tier -> target income rank
    income_scale: float = 2.0  # income factor = 1 - |rank - target| / scale
    aov_log2_scale: float = 2.0  # aov factor = 1 - |log2(price/aov)| / scale, price above AOV
    aov_below_log2_scale: float = 5.0  # same, price below AOV (fits inside a bigger basket: milder)
    # audience words, not what a store sells
    attribute_tags: list[str] = ["subscription", "dtc", "personalized", "sustainable", "natural", "organic",
                                 "non_toxic", "gifting", "women", "men", "mid-life"]
    no_category_penalty: float = 0.5  # fit *= this when the category level is attribute or none
    aov_gate_floor: float = 0.4  # when the price is known: fit *= floor + (1 - floor) * aov factor
    unknown_factor: float = 0.6  # factor value when the brief lacks the needed field
    # persona-affinity terms that are no publisher's category/subcategory -> the publisher category they
    # belong to; a brief category matching only this way scores same_category, an adjacent one scores
    # adjacent. Ambiguous terms (fitness, wellness, recovery, travel, small_batch, family/kids products,
    # subscription_*) stay out.
    affinity_parents: dict[str, str] = {
        "home_decor": "home", "home_goods": "home", "classic_apparel": "apparel", "fashion": "apparel",
        "sustainable_apparel": "apparel", "premium_basics": "apparel", "clean_beauty": "beauty",
        "organic_grocery": "groceries", "premium_grocery": "groceries", "gourmet_food": "groceries",
        "pet_health": "pet", "quick_commerce": "instant_delivery", "fitness_services": "wellness_services",
    }
    # subcategory words that mean the parent's kind of thing (Tailcrate's toys are pet toys): they count
    # only when the brief also names that category or another term in it
    scoped_terms: dict[str, str] = {"toys": "pet", "treats": "pet"}
    cutoff: float = 0.40
    max_recommended: int = 5
    # weak_fit only when no publisher clears the cutoff (the brief's examples #3, #13: single-publisher
    # categories proceed)
    weak_fit_min_recommended: int = 1
    weak_fit_show: int = 3


class PersonaTuning(BaseModel):
    # publishers: does this persona shop on the publishers picked in step 1 (their category and ages)?
    weights: dict[str, float] = {"affinity": 0.4, "price": 0.15, "age": 0.25, "publishers": 0.2}
    # family: parent/child term, sibling: same parent
    affinity_scores: dict[str, float] = {"direct": 1.0, "family": 0.7, "adjacent": 0.5, "sibling": 0.35}
    price_ideal: dict[str, float] = {"value": 2.0, "mid": 1.0, "premium": 0.5, "luxury": 0.0}  # price tier -> ideal price_rank
    price_scale: float = 2.0  # price factor = 1 - |ideal - price_rank| / scale
    conflict_penalty: float = 0.35
    age_mismatch_penalty: float = 0.2  # the brief states ages and this persona's range misses them (Gen Z for "women 35+")
    niche_penalty: float = 0.2  # a one-category persona (Pet Parent) with no affinity to the brief
    cutoff: float = 0.45
    min: int = 3
    max: int = 5
    mode_bonus: float = 0.15  # affinity = max(link, family) + this when the brief names the mode
    # personas whose data describes them by a mode, not a category
    attribute_affinities: dict[str, list[str]] = {
        "persona_010": ["gifting"],  # The Gifter: "any shopper within 30 days of a gifting holiday"
        "persona_006": ["sustainable"],  # The Sustainability Buyer
        "persona_007": ["subscription"],  # Convenience-First Millennial: "Heavy subscription user"
    }


class BudgetTuning(BaseModel):
    min_usd: float = 500.0
    max_usd: float = 5_000_000.0
    assumed_cpm_usd: float = 12.0  # CPM when a publisher's income tier isn't listed below
    cpm_by_income_usd: dict[str, float] = {"mid": 10.0, "mid-high": 13.0, "high": 16.0}  # richer audiences cost more
    learning_conversions_per_week: int = 50  # a CPA bid needs ~50 conversions a week per line item to leave learning
    weeks_per_month: int = 4  # so a month's goal is 200 conversions per line item
    round_to_usd: float = 500.0  # the recommended budget rounds up to a multiple of this


class BidTuning(BaseModel):
    cpa_fraction_of_order_value: float = 0.35
    guardrail_cpa_multiple: float = 1.5
    guardrail_min_impressions: int = 2000


class FrequencyCap(BaseModel):
    impressions: int
    per_days: int


class FrequencyTuning(BaseModel):
    # cap per person, by how considered the purchase is
    by_price_tier: dict[str, FrequencyCap] = {
        "value": FrequencyCap(impressions=5, per_days=7),
        "mid": FrequencyCap(impressions=4, per_days=7),
        "premium": FrequencyCap(impressions=3, per_days=14),
        "luxury": FrequencyCap(impressions=2, per_days=21),
        "unknown": FrequencyCap(impressions=3, per_days=7),
    }


class GateTuning(BaseModel):
    proceed_threshold: float = 0.70  # clarity below this -> clarify (fitted on train by evals/calibrate.py)
    no_signal_threshold: float = 0.30  # no business content below this -> no_signal
    business_threshold: float = 0.50  # a business or unshoppable buyer at or above this -> out_of_scope


class CreativeTuning(BaseModel):
    headline_max_chars: int = 60
    body_max_chars: int = 160
    cta_max_chars: int = 30
    headline_similarity: float = 0.8  # word overlap (Jaccard) at or above this counts as a duplicate headline
    # never in an ad unless the advertiser wrote them
    claim_words: list[str] = ["clinically", "proven", "cure", "guaranteed", "#1", "doctor", "vet-recommended",
                              "award"]
    # generic copy the playbook tells the Copywriter and the Critic to avoid
    banned_phrases: list[str] = ["high-quality", "perfect for", "look no further", "elevate", "unlock",
                                 "game-changer"]


class ClarifyTuning(BaseModel):
    max_questions: int = 3  # clarify questions kept from the LLM
    max_options: int = 5  # tap-able options kept per question
    min_options: int = 2  # a question with fewer options is dropped


class InputTuning(BaseModel):
    age_floor: int = 18  # fills a missing lower age bound ("under 35" -> 18-35)
    age_ceiling: int = 80  # fills a missing upper age bound ("over 50" -> 50-80)
    brief_age_max: int = 120  # the brief's ages are clamped to 0..this
    buyer_age_min: int = 18  # ages below this are the product's user, not the buyer


class RateLimitTuning(BaseModel):
    per_client_runs: int = 20  # live (paid) runs per client per window
    per_client_window_s: float = 600.0
    global_runs_per_hour: int = 200  # process-wide cap on live (paid) runs
    cost_campaign: int = 1  # runs charged per call: step 1
    cost_ads: int = 2  # step 3: up to 3 calls per persona
    cost_config_note: int = 1  # step 4 with a note (without one it's free)


class Tuning(BaseModel):
    llm_timeout_s: float = 25.0  # OpenAI client timeout per request (no SDK retries)
    publisher: PublisherTuning = PublisherTuning()
    persona: PersonaTuning = PersonaTuning()
    budget: BudgetTuning = BudgetTuning()
    bid: BidTuning = BidTuning()
    frequency: FrequencyTuning = FrequencyTuning()
    gate: GateTuning = GateTuning()
    creative: CreativeTuning = CreativeTuning()
    input: InputTuning = InputTuning()
    ratelimit: RateLimitTuning = RateLimitTuning()
    clarify: ClarifyTuning = ClarifyTuning()
