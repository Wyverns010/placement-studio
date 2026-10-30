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
