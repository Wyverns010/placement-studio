import pytest

from app.budget import allocate, target_cpa
from app.models import Factor, PublisherScore
from tests.conftest import CAT, T, brief


def ps(pid: str, fit: float) -> PublisherScore:
    return PublisherScore(publisher_id=pid, name=pid, fit=fit, factors=[], recommended=True,
                          stretch=False, reason="r")


def by_name(name: str) -> str:
    return next(p.id for p in CAT.publishers if p.name == name)


def test_shares_sum_to_one_and_respect_floor():
    pubs = [ps(by_name("Pawline"), 0.9), ps(by_name("Ruffco"), 0.8), ps(by_name("Tailcrate"), 0.02)]
    items, unalloc = allocate(pubs, CAT, 25000, T)
    assert sum(i.share for i in items) == pytest.approx(1.0, abs=1e-6)
    assert all(i.share >= T.budget.min_share - 1e-9 for i in items)
    assert sum(i.budget_usd for i in items) + unalloc == pytest.approx(25000, abs=0.05)


def test_budget_exceeds_reach_reports_unallocated():
    pubs = [ps(by_name("Pawline"), 0.9), ps(by_name("Tailcrate"), 0.6)]
    items, unalloc = allocate(pubs, CAT, 5_000_000, T)
    assert unalloc > 0
    for i in items:
        cap = CAT.publisher(i.publisher_id).monthly_impressions / 1000 * T.budget.assumed_cpm_usd
        assert i.budget_usd <= cap + 0.01


def test_allocation_independent_of_raw_text():
    pubs = [ps(by_name("Pawline"), 0.9), ps(by_name("Ruffco"), 0.5)]
    assert allocate(pubs, CAT, 25000, T) == allocate([p.model_copy() for p in pubs], CAT, 25000, T)


def test_empty_list():
    assert allocate([], CAT, 25000, T) == ([], 25000)


def test_single_publisher_gets_full_share():
    items, unalloc = allocate([ps(by_name("Pawline"), 0.7)], CAT, 1000, T)
    assert items[0].share == pytest.approx(1.0) and items[0].budget_usd == 1000 and unalloc == 0


def test_too_many_publishers_for_floor_falls_back_to_equal():
    pubs = [ps(p.id, 0.9 - 0.05 * i) for i, p in enumerate(CAT.publishers[:12])]
    items, _ = allocate(pubs, CAT, 1000, T)
    assert sum(i.share for i in items) == pytest.approx(1.0, abs=1e-6)
    assert max(i.share for i in items) == pytest.approx(min(i.share for i in items))


def test_target_cpa_subscription():
    b = brief(price_usd=60, business_model="subscription")
    assert target_cpa(b, [ps(by_name("Pawline"), 0.9)], CAT, T) == 42


def test_target_cpa_falls_back_to_weighted_aov():
    pub = CAT.publisher(by_name("Pawline"))
    got = target_cpa(brief(), [ps(pub.id, 0.9)], CAT, T)
    assert got == round(T.bid.cpa_fraction_of_order_value * pub.avg_order_value_usd)
