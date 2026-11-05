from __future__ import annotations

import pytest

from app.loaders import load_catalog, load_tuning
from app.models.brief import Brief

CAT = load_catalog()
T = load_tuning()


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


@pytest.fixture(autouse=True)
def _no_live_agents():
    """No test reaches a live model: the API's step-agent runtime is off (mode "code") unless a
    test overrides api.get_agent_runtime with a scripted one."""
    from app import api

    api.app.dependency_overrides[api.get_agent_runtime] = lambda: None
    yield
    api.app.dependency_overrides.pop(api.get_agent_runtime, None)
