import math

from app.match import _pick_reason, is_weak_fit, mark_stretch, score_publishers
from app.models import Factor
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


def test_age_overlap_partial_and_single_bound_filled():
    p = _pub("pub_007")  # 30-55
    lo, hi = 40, 70  # overlap 40-55 = 15 of 30 -> 0.5
    s = score_publishers(brief(age_min=lo, age_max=hi), CAT, T)
    aw = T.publisher.audience_weights
    u = T.publisher.unknown_factor
    assert abs(_f(s, "pub_007", "audience").score - (aw.age * 0.5 + aw.gender * u)) < 1e-9
    s = score_publishers(brief(age_min=40), CAT, T)  # one bound -> 40-80 (age_ceiling)
    assert T.audience.age_ceiling == 80
    assert abs(_f(s, "pub_007", "audience").score - (aw.age * 15 / 40 + aw.gender * u)) < 1e-9
    s = score_publishers(brief(age_max=40), CAT, T)  # 18-40 (age_floor): overlap 30-40 = 10 of 22
    assert abs(_f(s, "pub_007", "audience").score - (aw.age * 10 / 22 + aw.gender * u)) < 1e-9
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
    s = score_publishers(brief(categories=["pet"], price_usd=128), CAT, T)
    assert _pub("pub_007").avg_order_value_usd == 64
    assert abs(_f(s, "pub_007", "aov").score - 0.5) < 1e-9  # |log2(128/64)| = 1 -> 1 - 1/2
    for p in CAT.publishers:
        ratio = math.log2(128 / p.avg_order_value_usd)
        scale = T.publisher.aov_log2_scale if ratio >= 0 else T.publisher.aov_below_log2_scale
        want = max(0.0, 1 - abs(ratio) / scale)
        assert abs(_f(s, p.id, "aov").score - want) < 1e-9


def test_aov_penalises_price_below_basket_less_than_above():
    # a $16 item fits inside a $64 basket; a $256 item is far beyond what the audience spends
    pt = T.publisher
    assert pt.aov_below_log2_scale > pt.aov_log2_scale
    below = _f(score_publishers(brief(categories=["pet"], price_usd=16), CAT, T), "pub_007", "aov").score
    above = _f(score_publishers(brief(categories=["pet"], price_usd=256), CAT, T), "pub_007", "aov").score
    assert abs(below - (1 - 2 / pt.aov_below_log2_scale)) < 1e-9  # log2(16/64) = -2
    assert abs(above - max(0.0, 1 - 2 / pt.aov_log2_scale)) < 1e-9  # log2(256/64) = 2
    assert below > above


def test_aov_gate_not_applied_when_price_none():
    s = score_publishers(brief(categories=["pet"]), CAT, T)
    p = _by_id(s, "pub_007")
    w = T.publisher.weights
    want = sum(getattr(w, f.name) * f.score for f in p.factors)
    assert abs(p.fit - round(want, 3)) < 1e-9


def test_pick_reason_ignores_unknown_placeholders():
    fs = [Factor(name="category", score=0.5, note="Adjacent: x"),
          Factor(name="audience", score=0.6, note="Skews 1-2, 50% women"),
          Factor(name="income", score=0.6, note="Price tier unknown"),
          Factor(name="aov", score=0.6, note="Price unknown")]
    # placeholders (0.6) beat the known category (0.5) under max-over-all; must not win
    assert _pick_reason(fs, [False, True, True, True], True).note == "Adjacent: x"
    # excluded: weakest known, not weakest placeholder
    fs2 = [Factor(name="category", score=0.9, note="cat"), Factor(name="audience", score=0.3, note="aud"),
           Factor(name="income", score=0.1, note="Price tier unknown"), Factor(name="aov", score=0.2, note="Price unknown")]
    assert _pick_reason(fs2, [False, False, True, True], False).note == "aud"
    assert _pick_reason(fs2, [False, True, True, True], False).note == "cat"


def test_recommended_reason_is_never_a_placeholder_note():
    s = score_publishers(brief(categories=["pet_food"], adjacent_categories=["pet_health"]), CAT, T)
    recs = [p for p in s if p.recommended]
    assert recs and all(p.reason not in ("Price unknown", "Price tier unknown") for p in recs)
    assert _f(s, "pub_007", "income").note == "Price tier unknown"


def test_subscription_term_never_yields_same_category():
    s = score_publishers(brief(categories=["subscription"]), CAT, T)
    assert all(f.score <= T.publisher.category_scores.attribute
               for p in s for f in p.factors[:1])


# ---- persona-affinity terms mapped to their publisher category (tuning.publisher.affinity_parents) ----

def _candles(**over):
    base = dict(product="hand-poured candles", categories=["home_decor"], adjacent_categories=["gifting"],
                price_tier="premium", gender_skew="balanced")
    base.update(over)
    return brief(**base)


def test_affinity_parents_map_interest_terms_to_publisher_categories():
    m = T.publisher.affinity_parents
    assert m["home_decor"] == "home" and m["home_goods"] == "home"
    assert set(m) <= set(CAT.interest_terms())
    assert set(m.values()) <= set(CAT.vocab_groups())


def test_candles_with_only_an_interest_term_still_reach_home_publishers():
    scores = {s.name: s for s in score_publishers(_candles(), CAT, T)}
    for name in ("Northbed", "Hearthstone Goods"):
        s = scores[name]
        assert s.recommended and s.fit >= T.publisher.cutoff, (name, s.fit)
        cat = next(f for f in s.factors if f.name == "category")
        assert cat.score == T.publisher.category_scores.same_category
        assert cat.note == "Same category via home decor"
    assert not is_weak_fit(list(scores.values()), T)


def test_affinity_map_does_not_change_briefs_with_publisher_terms():
    t = T.model_copy(deep=True)
    t.publisher.affinity_parents = {}
    for b in (brief(product="protein bars", categories=["pantry"], adjacent_categories=["fitness", "wellness"],
                    price_tier="mid"),
              brief(product="dog food", categories=["pet_food"], adjacent_categories=["pet_health"]),
              _candles(categories=["home", "gifting"])):
        assert score_publishers(b, CAT, T) == score_publishers(b, CAT, t)


def test_adjacent_interest_terms_map_at_adjacent_level():
    b = _candles(categories=[], adjacent_categories=["home_goods", "home_decor"])
    scores = {s.name: s for s in score_publishers(b, CAT, T)}
    for name in ("Northbed", "Hearthstone Goods"):
        s = scores[name]
        assert s.recommended and s.fit >= T.publisher.cutoff, (name, s.fit)
        cat = next(f for f in s.factors if f.name == "category")
        assert cat.score == T.publisher.category_scores.adjacent and cat.note == "Adjacent via home goods"
    assert not is_weak_fit(list(scores.values()), T)


def test_named_subcategory_ranks_the_publisher_that_carries_it_first():
    # ceramic dinnerware reads as home + kitchen: Hearthstone (kitchen) beats Northbed (bedding)
    scores = {s.publisher_id: s for s in score_publishers(brief(categories=["home", "kitchen"]), CAT, T)}
    hearth, north = scores["pub_014"], scores["pub_011"]
    cat = lambda s: next(f for f in s.factors if f.name == "category")  # noqa: E731
    assert cat(hearth).score == T.publisher.category_scores.primary
    assert cat(north).score == T.publisher.category_scores.same_category
    assert cat(north).note == "Home category, but no kitchen"
    assert hearth.fit > north.fit
    plain = {s.publisher_id: s for s in score_publishers(brief(categories=["home"]), CAT, T)}
    assert cat(plain["pub_011"]).score == T.publisher.category_scores.primary


def test_weak_fit_stretch_picks_only_related_publishers():
    s = score_publishers(brief(categories=["beverages", "functional_beverages"], price_tier="value",
                               price_usd=3), CAT, T)
    picked = [p for p in mark_stretch(s, T) if p.recommended]
    assert picked and all(next(f for f in p.factors if f.name == "category").score > 0 for p in picked)


def test_audience_words_are_not_a_category_match():
    # "women" / "mid-life" describe shoppers: apparel stores tagged with them don't get skincare credit
    s = score_publishers(brief(categories=["skincare", "women", "mid-life"], adjacent_categories=[]), CAT, T)
    assert s[0].name == "Velvetline"
    assert all(_by_id(s, pid).factors[0].score <= T.publisher.category_scores.attribute
               for pid in ("pub_004", "pub_005"))  # Marlowe & Co., Linden Park


def test_kids_toys_do_not_match_pet_toys():
    s = score_publishers(brief(categories=["toys"], adjacent_categories=["kids_products"]), CAT, T)
    assert _by_id(s, "pub_018").factors[0].score == 0 and is_weak_fit(s, T)  # Tailcrate
    dog = score_publishers(brief(categories=["toys"], adjacent_categories=["pet"]), CAT, T)
    assert _by_id(dog, "pub_018").factors[0].score > 0.5
