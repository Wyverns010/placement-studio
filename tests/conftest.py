from __future__ import annotations

import pytest

from app.catalog import load_catalog
from app.models import Brief
from app.tuning import load_tuning

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


@pytest.fixture
def catalog():
    return CAT


@pytest.fixture
def tuning():
    return T
