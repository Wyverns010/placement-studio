from __future__ import annotations

import pytest

from app.match import _persona_raw, score_personas, select_personas
from tests.conftest import CAT, T, brief


def _persona(pid):
    return next(p for p in CAT.personas if p.id == pid)


def _by_id(scores, pid):
    return next(s for s in scores if s.persona_id == pid)


def _factor(score, name):
    return next(f for f in score.factors if f.name == name)


DOG = dict(categories=["pet_food"], adjacent_categories=["pet_health", "subscription"],
           price_tier="premium", business_model="subscription")


def test_dog_food_selects_pet_parent_first():
    scores = score_personas(brief(**DOG), CAT, T)
    assert len(scores) == 10
    assert scores[0].persona_id == "persona_004"
    sel = select_personas(scores, T)
    assert sel[0].persona_id == "persona_004" and 3 <= len(sel) <= 5


def test_factor_names_and_fit_bounds():
    for s in score_personas(brief(**DOG), CAT, T):
        assert [f.name for f in s.factors[:3]] == ["affinity", "price", "age"]
        assert 0.0 <= s.fit <= 1.0


def test_always_three_to_five_with_stretch_fill():
    scores = score_personas(brief(categories=["pet_food"], price_tier="luxury"), CAT, T)
    sel = select_personas(scores, T)
    assert 3 <= len(sel) <= 5
    for s in sel:
        assert s.stretch == (s.fit < T.persona.cutoff)
    assert any(s.stretch for s in sel)


def test_selection_does_not_mutate_inputs_and_caps_at_max():
    scores = score_personas(brief(categories=["beauty", "pet_food", "household", "apparel"],
                                  age_min=25, age_max=45), CAT, T)
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
    base, _ = _persona_raw(b, p, T)
    hit, factors = _persona_raw(c, p, T)
    assert base >= T.persona.conflict_penalty
    assert base - hit == pytest.approx(0.35)
    assert factors[3].name == "conflict" and factors[3].score == pytest.approx(-0.35)
    assert "luxury positioning" in factors[3].note
    # public scores show the conflict factor only for the affected persona
    s = score_personas(c, CAT, T)
    assert len(_by_id(s, "persona_002").factors) == 4
    assert len(_by_id(s, "persona_004").factors) == 3


def test_price_factor_premium_vs_sensitivity():
    s = score_personas(brief(price_tier="premium"), CAT, T)
    low = _factor(_by_id(s, "persona_004"), "price")       # price_rank 0.5 -> ideal
    high = _factor(_by_id(s, "persona_008"), "price")      # price_rank 2.0
    lux = _factor(_by_id(s, "persona_001"), "price")       # price_rank 0.0
    assert low.score == pytest.approx(1.0)
    assert lux.score == pytest.approx(0.75)
    assert high.score == pytest.approx(0.25)
    assert "premium" in low.note
    # value brief flips it
    v = score_personas(brief(price_tier="value"), CAT, T)
    assert _factor(_by_id(v, "persona_008"), "price").score == pytest.approx(1.0)
    assert _factor(_by_id(v, "persona_001"), "price").score == pytest.approx(0.0)


def test_unknown_price_and_age_use_placeholder():
    s = _by_id(score_personas(brief(), CAT, T), "persona_004")
    u = T.publisher.unknown_factor
    assert _factor(s, "price").score == u and _factor(s, "age").score == u


def test_attribute_tag_overlap_does_not_count_for_affinity():
    # persona_007 likes subscription_services (not an exact tag); craft a persona with a bare attribute tag
    p = _persona("persona_004").model_copy(update={"category_affinities": ["subscription", "natural"]})
    _, f = _persona_raw(brief(categories=["subscription"], adjacent_categories=["natural"]), p, T)
    assert f[0].name == "affinity" and f[0].score == 0.0 and f[0].note == "No affinity overlap"
    _, f = _persona_raw(brief(categories=["pet_food"]), _persona("persona_004"), T)
    assert f[0].score == T.persona.affinity_scores.direct and f[0].note == "Affinity: pet_food"


def test_adjacent_affinity_note():
    _, f = _persona_raw(brief(adjacent_categories=["pet_health"]), _persona("persona_004"), T)
    assert f[0].score == T.persona.affinity_scores.adjacent and f[0].note == "Adjacent affinity: pet_health"


def test_ties_broken_by_persona_id():
    scores = score_personas(brief(), CAT, T)
    keys = [(-s.fit, s.persona_id) for s in scores]
    assert keys == sorted(keys)


def test_conflict_penalty_visible_in_public_fit():
    kw = dict(categories=["pet_food"], price_tier="mid", age_min=32, age_max=45)
    a = _by_id(score_personas(brief(**kw), CAT, T), "persona_002").fit
    b = _by_id(score_personas(brief(conflicts=["luxury positioning"], **kw), CAT, T), "persona_002").fit
    assert a - b == pytest.approx(0.35)


def test_one_sided_age_is_filled_from_tuning():
    s = score_personas(brief(**DOG, age_min=50), CAT, T)
    for row in s:
        note = _factor(row, "age").note
        assert "None" not in note and "unknown" not in note
        assert note.endswith(f"vs 50–{T.audience.age_ceiling}")
    s = score_personas(brief(**DOG, age_max=30), CAT, T)
    assert _factor(s[0], "age").note.endswith(f"vs {T.audience.age_floor}–30")


def test_family_affinity_links_a_term_to_its_parent_category():
    # workout supplements read as wellness_dtc: supplements sits under it in the catalog
    s = _by_id(score_personas(brief(categories=["wellness_dtc"], price_tier="value"), CAT, T), "persona_009")
    f = _factor(s, "affinity")
    assert f.score == T.persona.affinity_scores.family and f.note == "Affinity: supplements (under wellness_dtc)"


def test_sibling_affinity_scores_below_family():
    sc = T.persona.affinity_scores
    assert sc.direct > sc.family > sc.sibling > 0
    # candles read as home: home_decor and home_goods both sit under home
    s = _by_id(score_personas(brief(categories=["home"]), CAT, T), "persona_005")
    assert _factor(s, "affinity").score == sc.family


def test_gifting_brief_reaches_the_gifter():
    s = _by_id(score_personas(brief(categories=["gifting"]), CAT, T), "persona_010")
    f = _factor(s, "affinity")
    assert f.score == T.persona.affinity_scores.family + T.persona.mode_bonus and f.note == "Shops for: gifting"


def test_niche_persona_is_penalised_only_without_affinity():
    golf = _by_id(score_personas(brief(categories=[], price_tier="premium"), CAT, T), "persona_004")
    assert _factor(golf, "niche").score == -T.persona.niche_penalty
    dog = _by_id(score_personas(brief(**DOG), CAT, T), "persona_004")
    assert all(f.name != "niche" for f in dog.factors)


def test_stretch_fill_prefers_personas_with_some_affinity():
    from app.models import Factor, PersonaScore

    def ps(pid, fit, aff):
        return PersonaScore(persona_id=pid, name=pid, fit=fit, stretch=False,
                            factors=[Factor(name="affinity", score=aff, note="")])
    scores = [ps("a", 0.6, 1.0), ps("b", 0.40, 0.0), ps("c", 0.38, 0.0), ps("d", 0.30, 0.35)]
    sel = select_personas(scores, T)
    assert [s.persona_id for s in sel] == ["a", "d", "b"]  # d has an affinity, so it beats a higher-fit b
    assert [s.stretch for s in sel] == [False, True, True]


def test_persona_outside_stated_ages_is_penalised():
    s = _by_id(score_personas(brief(categories=["apparel"], age_min=35), CAT, T), "persona_003")  # Gen Z 19-27
    assert _factor(s, "age_mismatch").score == -T.persona.age_mismatch_penalty
    unknown = _by_id(score_personas(brief(categories=["apparel"]), CAT, T), "persona_003")
    assert all(f.name != "age_mismatch" for f in unknown.factors)


def test_subscription_brief_reaches_the_convenience_first_millennial():
    # senior dog food on subscription: a heavy subscription user is the plausible third shopper
    sel = select_personas(score_personas(brief(**DOG), CAT, T), T)
    ids = [s.persona_id for s in sel]
    assert ids[:2] == ["persona_004", "persona_002"] and "persona_007" in ids
    assert "persona_009" not in ids  # the Fitness Enthusiast has no link to dog food


def test_shopping_mode_in_adjacent_counts_like_in_categories():
    # "mostly bought as gifts": the brief puts gifting next to the product, not as its category
    s = {p.name: p for p in score_personas(
        brief(categories=[], adjacent_categories=["gifting", "home_goods"], price_tier="premium"), CAT, T)}
    assert s["The Gifter"].factors[0].score == T.persona.affinity_scores.family + T.persona.mode_bonus
    assert s["The Gifter"].fit > s["The Affluent Classic"].fit
    # read as a home product, every home persona links at "family"; the gifting mode still wins
    home = score_personas(brief(categories=["home"], adjacent_categories=["home_goods", "gifting"],
                                price_tier="unknown"), CAT, T)
    assert home[0].name == "The Gifter" and home[0].fit > home[1].fit
