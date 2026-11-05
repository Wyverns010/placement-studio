from __future__ import annotations

from app.loaders import load_catalog
from app.models.brief import Brief
from app.models.tuning import Tuning

CAT = load_catalog()
T = Tuning()


def brief(**overrides) -> Brief:
    """A valid Brief with neutral defaults; override any field."""
    base = dict(
        describes_business=True,
        product="test product",
        audience_type="consumer",
        categories=[],
        adjacent_categories=[],
        conflicts=[],
        price_usd=None,
        price_tier="unknown",
        business_model="unknown",
        age_min=None,
        age_max=None,
        gender_skew="unknown",
        facts=[],
        unknowns=[],
        self_confidence=0.9,
    )
    base.update(overrides)
    return Brief(**base)


def make_deps(llm, limiter=None):
    """The app's shared objects with a fake LLM and a fresh rate limiter."""
    from app.api import Deps
    from app.ratelimit import RateLimiter
    limits = T.ratelimit
    return Deps(tuning=T, catalog=CAT, llm=llm,
                limiter=limiter or RateLimiter(limits.per_client_runs, limits.per_client_window_s))
