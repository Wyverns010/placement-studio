import math

import pytest

from app.match import (
    _persona_fit,
    pick_publishers,
    score_personas,
    score_publishers,
    select_personas,
)
from app.models.scores import Factor
from tests.conftest import CAT, T, brief


def test_senior_dog_food_ranks_pet_publishers_first():
    s = score_publishers(brief(categories=["pet_food"], adjacent_categories=["pet_health", "subscription"],
                               price_tier="premium", business_model="subscription"), CAT, T)
    top = [p.name for p in s if p.recommended]
    assert top[:2] == ["Pawline", "Ruffco"] or top[:2] == ["Ruffco", "Pawline"]
    assert all(p.name not in top for p in s if p.publisher_id in {"pub_005", "pub_013"})  # Linden Park, Velvetline


def test_ski_shells_are_weak_fit():
    assert pick_publishers(brief(categories=["apparel"], price_usd=650, price_tier="luxury"), CAT, T)[1]


def test_every_score_has_four_factors_and_reason():
    for p in score_publishers(brief(categories=["home"]), CAT, T):
        assert [f.name for f in p.factors] == ["category", "audience", "income", "aov"]
        assert p.reason and len(p.reason.split()) <= 8


def test_no_categories_yields_zero_category_factor():  # Review Focus 4
    s, weak = pick_publishers(brief(categories=[], adjacent_categories=[]), CAT, T)
    assert all(p.factors[0].score == 0 for p in s) and weak


def test_sorted_all_20_and_stretch_picks_are_copies():
    s = score_publishers(brief(categories=["apparel"], price_usd=650), CAT, T)
    assert len(s) == 20 and [p.fit for p in s] == sorted((p.fit for p in s), reverse=True)
    m, _ = pick_publishers(brief(categories=["apparel"], price_usd=650), CAT, T)
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
    return CAT.publisher_by_id[pid]


def test_age_overlap_partial_and_single_bound_filled():
    p = _pub("pub_007")  # 30-55
    lo, hi = 40, 70  # overlap 40-55 = 15 of 30 -> 0.5
    s = score_publishers(brief(age_min=lo, age_max=hi), CAT, T)
    aw = T.publisher.audience_weights
    u = T.publisher.unknown_factor
    assert abs(_f(s, "pub_007", "audience").score - (aw["age"] * 0.5 + aw["gender"] * u)) < 1e-9
    s = score_publishers(brief(age_min=40), CAT, T)  # one bound -> 40-80 (age_ceiling)
    assert T.input.age_ceiling == 80
    assert abs(_f(s, "pub_007", "audience").score - (aw["age"] * 15 / 40 + aw["gender"] * u)) < 1e-9
    s = score_publishers(brief(age_max=40), CAT, T)  # 18-40 (age_floor): overlap 30-40 = 10 of 22
    assert abs(_f(s, "pub_007", "audience").score - (aw["age"] * 10 / 22 + aw["gender"] * u)) < 1e-9
    assert p.age_min == 30 and p.age_max == 55


def test_age_equal_bounds_inside_and_outside():
    u = T.publisher.unknown_factor
    aw = T.publisher.audience_weights
    s = score_publishers(brief(age_min=40, age_max=40), CAT, T)
    assert abs(_f(s, "pub_007", "audience").score - (aw["age"] * 1 + aw["gender"] * u)) < 1e-9  # 30-55 contains 40
    s = score_publishers(brief(age_min=20, age_max=20), CAT, T)
    assert abs(_f(s, "pub_007", "audience").score - (aw["gender"] * u)) < 1e-9


def test_gender_female_uses_female_share():
    p = _pub("pub_007")
    aw = T.publisher.audience_weights
    s = score_publishers(brief(age_min=30, age_max=55, gender_skew="female"), CAT, T)
    assert abs(_f(s, "pub_007", "audience").score - (aw["age"] + aw["gender"] * p.audience.gender_split["female"])) < 1e-9


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
    want = sum(w[f.name] * f.score for f in p.factors)
    assert abs(p.fit - round(want, 3)) < 1e-9


def test_recommended_reason_is_never_a_placeholder_note():
    s = score_publishers(brief(categories=["pet_food"], adjacent_categories=["pet_health"]), CAT, T)
    recs = [p for p in s if p.recommended]
    assert recs and all(p.reason not in ("Price unknown", "Price tier unknown") for p in recs)
    assert _f(s, "pub_007", "income").note == "Price tier unknown"


def test_subscription_term_never_yields_same_category():
    s = score_publishers(brief(categories=["subscription"]), CAT, T)
    assert all(f.score <= T.publisher.category_scores["attribute"]
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
    assert set(m) <= set(CAT.interest_terms)
    assert set(m.values()) <= set(CAT.vocab_groups)


def test_candles_with_only_an_interest_term_still_reach_home_publishers():
    scores = {s.name: s for s in score_publishers(_candles(), CAT, T)}
    for name in ("Northbed", "Hearthstone Goods"):
        s = scores[name]
        assert s.recommended and s.fit >= T.publisher.cutoff, (name, s.fit)
        cat = next(f for f in s.factors if f.name == "category")
        assert cat.score == T.publisher.category_scores["same_category"]
        assert cat.note == "Same category via home decor"
    assert sum(s.recommended for s in scores.values()) >= T.publisher.weak_fit_min_recommended


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
        assert cat.score == T.publisher.category_scores["adjacent"] and cat.note == "Adjacent via home goods"
    assert sum(s.recommended for s in scores.values()) >= T.publisher.weak_fit_min_recommended


def test_named_subcategory_ranks_the_publisher_that_carries_it_first():
    # ceramic dinnerware reads as home + kitchen: Hearthstone (kitchen) beats Northbed (bedding)
    scores = {s.publisher_id: s for s in score_publishers(brief(categories=["home", "kitchen"]), CAT, T)}
    hearth, north = scores["pub_014"], scores["pub_011"]
    cat = lambda s: next(f for f in s.factors if f.name == "category")  # noqa: E731
    assert cat(hearth).score == T.publisher.category_scores["primary"]
    assert cat(north).score == T.publisher.category_scores["same_category"]
    assert cat(north).note == "Home category, but no kitchen"
    assert hearth.fit > north.fit
    plain = {s.publisher_id: s for s in score_publishers(brief(categories=["home"]), CAT, T)}
    assert cat(plain["pub_011"]).score == T.publisher.category_scores["primary"]


def test_weak_fit_stretch_picks_only_related_publishers():
    s, _ = pick_publishers(brief(categories=["beverages", "functional_beverages"], price_tier="value",
                                 price_usd=3), CAT, T)
    picked = [p for p in s if p.recommended]
    assert picked and all(next(f for f in p.factors if f.name == "category").score > 0 for p in picked)


def test_audience_words_are_not_a_category_match():
    # "women" / "mid-life" describe shoppers: apparel stores tagged with them don't get skincare credit
    s = score_publishers(brief(categories=["skincare", "women", "mid-life"], adjacent_categories=[]), CAT, T)
    assert s[0].name == "Velvetline"
    assert all(_by_id(s, pid).factors[0].score <= T.publisher.category_scores["attribute"]
               for pid in ("pub_004", "pub_005"))  # Marlowe & Co., Linden Park


def test_kids_toys_do_not_match_pet_toys():
    s, weak = pick_publishers(brief(categories=["toys"], adjacent_categories=["kids_products"]), CAT, T)
    assert _by_id(s, "pub_018").factors[0].score == 0 and weak  # Tailcrate
    dog = score_publishers(brief(categories=["toys"], adjacent_categories=["pet"]), CAT, T)
    assert _by_id(dog, "pub_018").factors[0].score > 0.5


def test_pick_publishers_marks_stretch_when_weak():
    from app.match import pick_publishers
    scores, weak = pick_publishers(brief(categories=["apparel"], price_usd=650, price_tier="luxury"), CAT, T, set())
    assert weak
    picked = [s for s in scores if s.recommended]
    assert picked and all(s.stretch for s in picked) and len(picked) <= T.publisher.weak_fit_show


# ---- personas ----


def _persona(pid):
    return next(p for p in CAT.personas if p.id == pid)


def _persona_by_id(scores, pid):
    return next(s for s in scores if s.persona_id == pid)


def _factor(score, name):
    return next(f for f in score.factors if f.name == name)


DOG = dict(categories=["pet_food"], adjacent_categories=["pet_health", "subscription"],
           price_tier="premium", business_model="subscription")


def test_dog_food_selects_pet_parent_first():
    scores = score_personas(brief(**DOG), CAT, T, [])
    assert len(scores) == 10
    assert scores[0].persona_id == "persona_004"
    sel = select_personas(scores, T)
    assert sel[0].persona_id == "persona_004" and 3 <= len(sel) <= 5


def test_factor_names_and_fit_bounds():
    for s in score_personas(brief(**DOG), CAT, T, []):
        assert [f.name for f in s.factors[:3]] == ["affinity", "price", "age"]
        assert 0.0 <= s.fit <= 1.0


def test_always_three_to_five_with_stretch_fill():
    scores = score_personas(brief(categories=["pet_food"], price_tier="luxury"), CAT, T, [])
    sel = select_personas(scores, T)
    assert 3 <= len(sel) <= 5
    for s in sel:
        assert s.stretch == (s.fit < T.persona.cutoff)
    assert any(s.stretch for s in sel)


def test_selection_does_not_mutate_inputs_and_caps_at_max():
    scores = score_personas(brief(categories=["beauty", "pet_food", "household", "apparel"],
                                  age_min=25, age_max=45), CAT, T, [])
    snapshot = [s.model_copy(deep=True) for s in scores]
    sel = select_personas(scores, T)
    assert len(sel) <= T.persona.max
    assert scores == snapshot
    assert all(not s.stretch for s in scores)


def test_conflict_penalty_applies():
    b = brief(categories=["pet_food"], price_tier="mid", age_min=32, age_max=45)
    c = brief(categories=["pet_food"], price_tier="mid", age_min=32, age_max=45,
              conflicts=["luxury positioning"])
    p = _persona("persona_002")
    base, _ = _persona_fit(b, p, [], {}, T)
    hit, factors = _persona_fit(c, p, [], {}, T)
    assert base >= T.persona.conflict_penalty
    assert base - hit == pytest.approx(0.35)
    assert factors[4].name == "conflict" and factors[4].score == pytest.approx(-0.35)
    assert "luxury positioning" in factors[4].note
    # public scores show the conflict factor only for the affected persona
    s = score_personas(c, CAT, T, [])
    assert len(_persona_by_id(s, "persona_002").factors) == 5
    assert len(_persona_by_id(s, "persona_004").factors) == 4


def test_price_factor_premium_vs_sensitivity():
    s = score_personas(brief(price_tier="premium"), CAT, T, [])
    low = _factor(_persona_by_id(s, "persona_004"), "price")       # price_rank 0.5 -> ideal
    high = _factor(_persona_by_id(s, "persona_008"), "price")      # price_rank 2.0
    lux = _factor(_persona_by_id(s, "persona_001"), "price")       # price_rank 0.0
    assert low.score == pytest.approx(1.0)
    assert lux.score == pytest.approx(0.75)
    assert high.score == pytest.approx(0.25)
    assert "premium" in low.note
    # value brief flips it
    v = score_personas(brief(price_tier="value"), CAT, T, [])
    assert _factor(_persona_by_id(v, "persona_008"), "price").score == pytest.approx(1.0)
    assert _factor(_persona_by_id(v, "persona_001"), "price").score == pytest.approx(0.0)


def test_unknown_price_and_age_use_placeholder():
    s = _persona_by_id(score_personas(brief(), CAT, T, []), "persona_004")
    u = T.publisher.unknown_factor
    assert _factor(s, "price").score == u and _factor(s, "age").score == u


def test_attribute_tag_overlap_does_not_count_for_affinity():
    # persona_007 likes subscription_services (not an exact tag); craft a persona with a bare attribute tag
    p = _persona("persona_004").model_copy(update={"category_affinities": ["subscription", "natural"]})
    _, f = _persona_fit(brief(categories=["subscription"], adjacent_categories=["natural"]), p, [], {}, T)
    assert f[0].name == "affinity" and f[0].score == 0.0 and f[0].note == "No affinity overlap"
    _, f = _persona_fit(brief(categories=["pet_food"]), _persona("persona_004"), [], {}, T)
    assert f[0].score == T.persona.affinity_scores["direct"] and f[0].note == "Affinity: pet_food"


def test_adjacent_affinity_note():
    _, f = _persona_fit(brief(adjacent_categories=["pet_health"]), _persona("persona_004"), [], {}, T)
    assert f[0].score == T.persona.affinity_scores["adjacent"] and f[0].note == "Adjacent affinity: pet_health"


def test_ties_broken_by_persona_id():
    scores = score_personas(brief(), CAT, T, [])
    keys = [(-s.fit, s.persona_id) for s in scores]
    assert keys == sorted(keys)


def test_conflict_penalty_visible_in_public_fit():
    kw = dict(categories=["pet_food"], price_tier="mid", age_min=32, age_max=45)
    a = _persona_by_id(score_personas(brief(**kw), CAT, T, []), "persona_002").fit
    b = _persona_by_id(score_personas(brief(conflicts=["luxury positioning"], **kw), CAT, T, []), "persona_002").fit
    assert a - b == pytest.approx(0.35)


def test_one_sided_age_is_filled_from_tuning():
    s = score_personas(brief(**DOG, age_min=50), CAT, T, [])
    for row in s:
        note = _factor(row, "age").note
        assert "None" not in note and "unknown" not in note
        assert note.endswith(f"vs 50–{T.input.age_ceiling}")
    s = score_personas(brief(**DOG, age_max=30), CAT, T, [])
    assert _factor(s[0], "age").note.endswith(f"vs {T.input.age_floor}–30")


def test_family_affinity_links_a_term_to_its_parent_category():
    # workout supplements read as wellness_dtc: supplements sits under it in the catalog
    s = _persona_by_id(score_personas(brief(categories=["wellness_dtc"], price_tier="value"), CAT, T, []), "persona_009")
    f = _factor(s, "affinity")
    assert f.score == T.persona.affinity_scores["family"] and f.note == "Affinity: supplements (under wellness_dtc)"


def test_sibling_affinity_scores_below_family():
    sc = T.persona.affinity_scores
    assert sc["direct"] > sc["family"] > sc["sibling"] > 0
    # candles read as home: home_decor and home_goods both sit under home
    s = _persona_by_id(score_personas(brief(categories=["home"]), CAT, T, []), "persona_005")
    assert _factor(s, "affinity").score == sc["family"]


def test_gifting_brief_reaches_the_gifter():
    s = _persona_by_id(score_personas(brief(categories=["gifting"]), CAT, T, []), "persona_010")
    f = _factor(s, "affinity")
    assert f.score == T.persona.affinity_scores["family"] + T.persona.mode_bonus and f.note == "Shops for: gifting"


def test_niche_persona_is_penalised_only_without_affinity():
    golf = _persona_by_id(score_personas(brief(categories=[], price_tier="premium"), CAT, T, []), "persona_004")
    assert _factor(golf, "niche").score == -T.persona.niche_penalty
    dog = _persona_by_id(score_personas(brief(**DOG), CAT, T, []), "persona_004")
    assert all(f.name != "niche" for f in dog.factors)


def test_stretch_fill_prefers_personas_with_some_affinity():
    from app.models.scores import PersonaScore

    def ps(pid, fit, aff):
        return PersonaScore(persona_id=pid, name=pid, fit=fit, stretch=False,
                            factors=[Factor(name="affinity", score=aff, note="")])
    scores = [ps("a", 0.6, 1.0), ps("b", 0.40, 0.0), ps("c", 0.38, 0.0), ps("d", 0.30, 0.35)]
    sel = select_personas(scores, T)
    assert [s.persona_id for s in sel] == ["a", "d", "b"]  # d has an affinity, so it beats a higher-fit b
    assert [s.stretch for s in sel] == [False, True, True]


def test_persona_outside_stated_ages_is_penalised():
    s = _persona_by_id(score_personas(brief(categories=["apparel"], age_min=35), CAT, T, []), "persona_003")  # Gen Z 19-27
    assert _factor(s, "age_mismatch").score == -T.persona.age_mismatch_penalty
    unknown = _persona_by_id(score_personas(brief(categories=["apparel"]), CAT, T, []), "persona_003")
    assert all(f.name != "age_mismatch" for f in unknown.factors)


def test_subscription_brief_reaches_the_convenience_first_millennial():
    # senior dog food on subscription: a heavy subscription user is the plausible third shopper
    sel = select_personas(score_personas(brief(**DOG), CAT, T, []), T)
    ids = [s.persona_id for s in sel]
    assert ids[:2] == ["persona_004", "persona_002"] and "persona_007" in ids
    assert "persona_009" not in ids  # the Fitness Enthusiast has no link to dog food


def test_shopping_mode_in_adjacent_counts_like_in_categories():
    # "mostly bought as gifts": the brief puts gifting next to the product, not as its category
    s = {p.name: p for p in score_personas(
        brief(categories=[], adjacent_categories=["gifting", "home_goods"], price_tier="premium"), CAT, T, [])}
    assert s["The Gifter"].factors[0].score == T.persona.affinity_scores["family"] + T.persona.mode_bonus
    assert s["The Gifter"].fit > s["The Affluent Classic"].fit
    # read as a home product, every home persona links at "family"; the gifting mode still wins
    home = score_personas(brief(categories=["home"], adjacent_categories=["home_goods", "gifting"],
                                price_tier="unknown"), CAT, T, [])
    assert home[0].name == "The Gifter" and home[0].fit > home[1].fit


def test_personas_are_scored_against_the_picked_publishers():
    from app.match import score_publishers
    b = brief(categories=["bedding", "home_textiles"], adjacent_categories=["home_goods"],
              price_tier="premium")
    recs = [p for p in score_publishers(b, CAT, T) if p.recommended]
    with_pubs = {p.name: p for p in score_personas(b, CAT, T, recs)}
    affluent = with_pubs["The Affluent Classic"]
    shop = next(f for f in affluent.factors if f.name == "publishers")
    assert shop.score > 0.4 and "Northbed" in shop.note  # home_goods sits under Northbed's category
    # a persona with no link to these publishers gets less from the factor
    golf = next(f for f in with_pubs["The Pet Parent"].factors if f.name == "publishers")
    assert golf.score < shop.score
