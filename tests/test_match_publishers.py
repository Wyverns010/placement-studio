from app.match import is_weak_fit, mark_stretch, score_publishers
from tests.conftest import CAT, T, brief


def test_senior_dog_food_ranks_pet_publishers_first():
    s = score_publishers(brief(categories=["pet_food"], adjacent_categories=["pet_health", "subscription"],
                               price_tier="premium", business_model="subscription"), CAT, T)
    top = [p.name for p in s if p.recommended]
    assert top[:2] == ["Pawline", "Ruffco"] or top[:2] == ["Ruffco", "Pawline"]
    assert all(p.name not in top for p in s if p.publisher_id in {"pub_005", "pub_013"})  # Linden Park, Velvetline


def test_ski_shells_are_weak_fit():
    s = score_publishers(brief(categories=["apparel"], price_usd=650, price_tier="luxury"), CAT, T)
    assert is_weak_fit(s, T)


def test_every_score_has_four_factors_and_reason():
    for p in score_publishers(brief(categories=["home"]), CAT, T):
        assert [f.name for f in p.factors] == ["category", "audience", "income", "aov"]
        assert p.reason and len(p.reason.split()) <= 8


def test_no_categories_yields_zero_category_factor():  # Review Focus 4
    s = score_publishers(brief(categories=[], adjacent_categories=[]), CAT, T)
    assert all(p.factors[0].score == 0 for p in s) and is_weak_fit(s, T)


def test_sorted_all_20_and_mark_stretch_copies():
    s = score_publishers(brief(categories=["apparel"], price_usd=650), CAT, T)
    assert len(s) == 20 and [p.fit for p in s] == sorted((p.fit for p in s), reverse=True)
    m = mark_stretch(s, T)
    assert [p.stretch for p in m].count(True) == T.publisher.weak_fit_show
    assert all(p.recommended == p.stretch for p in m)
    assert not any(p.stretch for p in s)


def _dog_food():
    return brief(categories=["pet_food"], adjacent_categories=["pet_health", "subscription"],
                 price_tier="premium", business_model="subscription")


def _by_id(scores, pid):
    return next(p for p in scores if p.publisher_id == pid)


def test_same_category_parent_match():
    tail = _by_id(score_publishers(_dog_food(), CAT, T), "pub_018")
    assert tail.factors[0].score == 0.70 and tail.recommended


def test_attribute_only_match_is_penalized():
    move = _by_id(score_publishers(_dog_food(), CAT, T), "pub_002")
    assert move.factors[0].score == 0.20 and not move.recommended


def test_dog_food_top3_are_pet_publishers():
    s = score_publishers(_dog_food(), CAT, T)
    assert {p.publisher_id for p in [p for p in s if p.recommended][:3]} == {"pub_007", "pub_009", "pub_018"}


def _f(scores, pid, name):
    return next(f for f in _by_id(scores, pid).factors if f.name == name)


def _pub(pid):
    return CAT.publisher(pid)


def test_age_overlap_partial_and_single_bound_unknown():
    p = _pub("pub_007")  # 30-55
    lo, hi = 40, 70  # overlap 40-55 = 15 of 30 -> 0.5
    s = score_publishers(brief(age_min=lo, age_max=hi), CAT, T)
    aw = T.publisher.audience_weights
    u = T.publisher.unknown_factor
    assert abs(_f(s, "pub_007", "audience").score - (aw.age * 0.5 + aw.gender * u)) < 1e-9
    s = score_publishers(brief(age_min=40), CAT, T)  # single bound -> unknown
    assert abs(_f(s, "pub_007", "audience").score - u) < 1e-9
    assert p.age_min == 30 and p.age_max == 55


def test_age_equal_bounds_inside_and_outside():
    u = T.publisher.unknown_factor
    aw = T.publisher.audience_weights
    s = score_publishers(brief(age_min=40, age_max=40), CAT, T)
    assert abs(_f(s, "pub_007", "audience").score - (aw.age * 1 + aw.gender * u)) < 1e-9  # 30-55 contains 40
    s = score_publishers(brief(age_min=20, age_max=20), CAT, T)
    assert abs(_f(s, "pub_007", "audience").score - (aw.gender * u)) < 1e-9


def test_gender_female_uses_female_share():
    p = _pub("pub_007")
    aw = T.publisher.audience_weights
    s = score_publishers(brief(age_min=30, age_max=55, gender_skew="female"), CAT, T)
    assert abs(_f(s, "pub_007", "audience").score - (aw.age + aw.gender * p.audience.gender_split["female"])) < 1e-9


def test_income_target_premium_vs_high_and_mid():
    s = score_publishers(brief(price_tier="premium"), CAT, T)
    by_rank = {}
    for pub in CAT.publishers:
        by_rank.setdefault(pub.income_rank, _f(s, pub.id, "income").score)
    assert by_rank == {1: 0.25, 2: 0.75, 3: 0.75}  # target 2.5, scale 2


def test_aov_log2_and_gate():
    pub = next(p for p in CAT.publishers if p.avg_order_value_usd == 64) if any(
        p.avg_order_value_usd == 64 for p in CAT.publishers) else None
    s = score_publishers(brief(categories=["pet"], price_usd=128), CAT, T)
    for p in CAT.publishers:
        import math
        want = max(0.0, 1 - abs(math.log2(128 / p.avg_order_value_usd)) / T.publisher.aov_log2_scale)
        assert abs(_f(s, p.id, "aov").score - want) < 1e-9
    if pub:
        assert abs(_f(s, pub.id, "aov").score - 0.5) < 1e-9


def test_aov_gate_not_applied_when_price_none():
    s = score_publishers(brief(categories=["pet"]), CAT, T)
    p = _by_id(s, "pub_007")
    w = T.publisher.weights
    want = sum(getattr(w, f.name) * f.score for f in p.factors)
    assert abs(p.fit - round(want, 3)) < 1e-9


def test_reason_skips_unknown_placeholder_factors():
    s = score_publishers(brief(categories=["pet_food"]), CAT, T)  # price, tier, age, gender unknown
    top = _by_id(s, "pub_007")
    assert top.recommended and top.reason == "Pet food subcategory match"
    assert _f(s, "pub_007", "income").note == "Price tier unknown"


def test_subscription_term_never_yields_same_category():
    s = score_publishers(brief(categories=["subscription"]), CAT, T)
    assert all(f.score <= T.publisher.category_scores.attribute
               for p in s for f in p.factors[:1])
