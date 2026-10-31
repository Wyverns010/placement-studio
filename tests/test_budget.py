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


# ---- recommended budget, frequency and pacing from economics (config/tuning.yaml) ----

from app.budget import frequency_cap, pacing, recommended_budget  # noqa: E402

PAW, RUFF, TAIL = by_name("Pawline"), by_name("Ruffco"), by_name("Tailcrate")


def test_conversions_per_line_item_and_rounding_are_tunables():
    assert T.budget.conversions_per_line_item == 50 and T.budget.round_to_usd == 500


def test_recommended_is_cpa_times_conversions_per_publisher_rounded_to_500():
    # price $60 one-off -> CPA round(0.35 x 60) = $21 -> $21 x 50 = $1,050 per publisher
    rec = recommended_budget(brief(price_usd=60), [ps(PAW, 0.9), ps(RUFF, 0.8)], CAT, False, T)
    assert rec.cpa == 21 and rec.per_publisher == [1050, 1050]
    assert rec.full_usd == 2000 and rec.usd == 2000  # 2,100 rounds to the nearest $500


def test_recommended_capped_at_each_publishers_reach():
    # CPA $3,500 -> $175,000 wanted per publisher; Pawline can only absorb $57,600 at $12 CPM
    rec = recommended_budget(brief(price_usd=10000), [ps(PAW, 0.9), ps(RUFF, 0.8)], CAT, False, T)
    assert rec.per_publisher == [57600, 175000]
    assert rec.usd == 232500


@pytest.mark.parametrize("price,n_pubs,want", [(1, 1, 500), (5, 1, 500), (10**7, 3, None)])
def test_recommended_clamped_to_budget_bounds(price, n_pubs, want):
    pubs = [ps(p.id, 0.5) for p in CAT.publishers[:n_pubs]]
    rec = recommended_budget(brief(price_usd=price), pubs, CAT, False, T)
    assert T.budget.min_usd <= rec.usd <= T.budget.max_usd
    if want is not None:
        assert rec.usd == want


def test_weak_fit_recommends_a_20_percent_test():
    pubs = [ps(PAW, 0.3), ps(RUFF, 0.3), ps(TAIL, 0.3)]
    rec = recommended_budget(brief(price_usd=80), pubs, CAT, True, T)  # $28 x 50 x 3 = 4,200 -> 4,000
    assert rec.full_usd == 4000 and rec.usd == 800
    small = recommended_budget(brief(price_usd=60), pubs[:2], CAT, True, T)  # 2,000 x 20% = 400
    assert small.usd == T.budget.min_usd


@pytest.mark.parametrize("tier,want", [("value", (5, 7)), ("mid", (4, 7)), ("premium", (3, 14)),
                                       ("luxury", (2, 21)), ("unknown", (3, 7))])
def test_frequency_by_price_tier(tier, want):
    assert frequency_cap(brief(price_tier=tier), False, T) == want


def test_frequency_subscription_adds_one_and_weak_fit_takes_one_off():
    assert frequency_cap(brief(price_tier="mid", business_model="subscription"), False, T) == (5, 7)
    assert frequency_cap(brief(price_tier="mid"), True, T) == (3, 7)
    assert frequency_cap(brief(price_tier="luxury"), True, T) == (1, 21)


def test_frequency_never_below_one():
    t = T.model_copy(deep=True)
    t.frequency.weak_fit_reduction = 5
    assert frequency_cap(brief(price_tier="luxury"), True, t)[0] == 1


@pytest.mark.parametrize("tier,weak,monthly,rec,want", [
    ("mid", True, 500, 500, "front_loaded"),
    ("luxury", True, 500, 500, "front_loaded"),
    ("luxury", False, 1000, 5000, "even"),
    ("premium", False, 1000, 5000, "even"),
    ("value", False, 1000, 5000, "accelerated"),
    ("mid", False, 1000, 5000, "accelerated"),
    ("mid", False, 5000, 5000, "even"),
    ("value", False, 9000, 5000, "even"),
    ("unknown", False, 1000, 5000, "even"),
])
def test_pacing_rules(tier, weak, monthly, rec, want):
    assert pacing(brief(price_tier=tier), weak, monthly, rec) == want
