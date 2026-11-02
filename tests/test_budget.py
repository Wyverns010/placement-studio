import pytest

from app.budget import allocate, reach_cap_usd, target_cpa
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
        cap = reach_cap_usd(CAT.publisher(i.publisher_id), T)
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


def test_conversion_goal_and_rounding_are_tunables():
    b = T.budget
    assert b.learning_conversions_per_week == 50 and b.weeks_per_month == 4
    assert b.conversions_per_month == 200 and b.round_to_usd == 500


def test_cpm_and_reach_follow_the_publishers_audience():
    paw, ruff = CAT.publisher(PAW), CAT.publisher(RUFF)  # mid-high 4.8M, mid 62M impressions
    assert reach_cap_usd(paw, T) == 4_800_000 * 0.25 / 1000 * 13 == 15600
    assert reach_cap_usd(ruff, T) == 62_000_000 * 0.25 / 1000 * 10 == 155000


def test_recommended_is_cpa_times_monthly_conversions_per_publisher_rounded_up():
    # price $60 one-off -> CPA round(0.35 x 60) = $21 -> $21 x 200 = $4,200 per publisher
    rec = recommended_budget(brief(price_usd=60), [ps(PAW, 0.9), ps(RUFF, 0.8)], CAT, False, T)
    assert rec.cpa == 21 and rec.per_publisher == [4200, 4200] and rec.capped == []
    assert rec.full_usd == 8500 and rec.usd == 8500  # 8,400 rounds up: enough for the 200


def test_recommended_capped_at_each_publishers_reach():
    # CPA $3,500 -> $700,000 wanted per publisher; both can only absorb their reach
    rec = recommended_budget(brief(price_usd=10000), [ps(PAW, 0.9), ps(RUFF, 0.8)], CAT, False, T)
    assert rec.per_publisher == [15600, 155000] and rec.capped == [PAW, RUFF]
    assert rec.usd == 171000  # 170,600 rounded up


@pytest.mark.parametrize("price,n_pubs,want", [(1, 1, 500), (5, 1, 500), (10**7, 3, None)])
def test_recommended_clamped_to_budget_bounds(price, n_pubs, want):
    pubs = [ps(p.id, 0.5) for p in CAT.publishers[:n_pubs]]
    rec = recommended_budget(brief(price_usd=price), pubs, CAT, False, T)
    assert T.budget.min_usd <= rec.usd <= T.budget.max_usd
    if want is not None:
        assert rec.usd == want


def test_weak_fit_recommends_a_20_percent_test():
    pubs = [ps(PAW, 0.3), ps(RUFF, 0.3), ps(TAIL, 0.3)]
    rec = recommended_budget(brief(price_usd=80), pubs, CAT, True, T)  # $28 x 200 x 3 = 16,800
    assert rec.full_usd == 17000 and rec.usd == 3000  # 20% = 3,400, capped at the $3,000 test max
    small = recommended_budget(brief(price_usd=5), pubs[:2], CAT, True, T)  # $2 x 400 = 800 -> 1,000 x 20%
    assert small.usd == T.budget.min_usd


def test_weak_fit_test_capped_and_rounded():
    assert T.budget.weak_fit_test_max_usd == 3000
    pubs = [ps(PAW, 0.3), ps(RUFF, 0.3), ps(TAIL, 0.3)]
    big = recommended_budget(brief(price_usd=1000), pubs, CAT, True, T)  # full >> cap
    assert big.full_usd > 15000 and big.usd == 3000
    # the test share rounds to the nearest $500, never an odd figure
    t = T.model_copy(deep=True)
    t.budget.weak_fit_test_fraction = 0.1  # 0.1 x 17,000 = 1,700 -> 1,500
    odd = recommended_budget(brief(price_usd=80), pubs, CAT, True, t)
    assert odd.usd % t.budget.round_to_usd == 0 and odd.usd == 1500


def test_round_to_usd_must_be_positive():
    import yaml
    from pydantic import ValidationError
    from app.tuning import Tuning
    raw = yaml.safe_load(open("config/tuning.yaml"))
    raw["budget"]["round_to_usd"] = 0
    with pytest.raises(ValidationError):
        Tuning(**raw)


@pytest.mark.parametrize("tier,want", [("value", (5, 7)), ("mid", (4, 7)), ("premium", (3, 14)),
                                       ("luxury", (2, 21)), ("unknown", (3, 7))])
def test_frequency_by_price_tier(tier, want):
    assert frequency_cap(brief(price_tier=tier), False, T) == want


def test_frequency_subscription_adds_one_and_weak_fit_takes_one_off():
    assert frequency_cap(brief(price_tier="mid", business_model="subscription"), False, T) == (5, 7)
    assert frequency_cap(brief(price_tier="mid"), True, T) == (3, 7)
    assert frequency_cap(brief(price_tier="luxury"), True, T) == (1, 14)


def test_weak_fit_frequency_window_capped_for_a_short_test():
    assert T.frequency.weak_fit_max_per_days == 14
    assert frequency_cap(brief(price_tier="premium"), True, T) == (2, 14)
    assert frequency_cap(brief(price_tier="value"), True, T) == (4, 7)  # shorter windows unchanged
    assert frequency_cap(brief(price_tier="luxury"), False, T) == (2, 21)


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


def test_projection_is_plain_arithmetic_on_the_line_items():
    from app.budget import projection
    pubs = [ps(PAW, 0.9), ps(RUFF, 0.8)]
    items, _ = allocate(pubs, CAT, 10_000, T)
    p = projection(items, 40, 100, T)
    assert p.impressions == sum(li.est_impressions for li in items)
    assert p.conversions == 250 and p.revenue_usd == 25_000 and p.roas == 2.5
    assert p.conversions_per_1k == round(250 / p.impressions * 1000, 2) and not p.stretch
    assert projection(items, 1, 100, T).stretch  # a $1 CPA needs far too many conversions
