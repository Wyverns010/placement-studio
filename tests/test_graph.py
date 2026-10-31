"""The shopper-graph matcher (app/graph.py, match.impl: graph): the graph built from the data pack,
the weighted walk from a brief's categories, and the switch in app/match.py."""
from __future__ import annotations

from app import graph as G
from app.match import is_weak_fit, score_personas, score_publishers, select_personas
from tests.conftest import CAT, T, brief


def _graph_t():
    t = T.model_copy(deep=True)
    t.match.impl = "graph"
    return t


TG = _graph_t()
GR = G.build_graph(CAT, T)


def _by_name(scores):
    return {s.name: s for s in scores}


# ---- the graph ----

def test_graph_has_every_publisher_persona_and_vocab_term():
    kinds = {n: G.kind(n) for n in GR.adj}
    assert sum(k == "publisher" for k in kinds.values()) == 20
    assert sum(k == "persona" for k in kinds.values()) == 10
    assert {G.term(v) for v in CAT.vocab} <= set(GR.adj)


def test_publisher_edges_carry_tuning_weights():
    e = T.graph.edges
    pawline = G.pub("pub_007")
    assert GR.adj[pawline][G.term("pet")] == e.primary
    assert GR.adj[pawline][G.term("pet_food")] == e.subcategory
    assert GR.adj[pawline][G.term("subscription")] == e.attribute  # attribute tags stay weak
    assert GR.adj[G.term("pet")][pawline] == e.primary  # undirected


def test_subcategory_and_affinity_parent_links():
    e = T.graph.edges
    assert GR.adj[G.term("pet_food")][G.term("pet")] == e.parent
    assert GR.adj[G.term("home_decor")][G.term("home")] == e.parent  # tuning affinity_parents
    assert G.term("subscription") not in GR.adj[G.term("pet")]  # attribute tags get no parent link


def test_persona_affinity_edges():
    assert GR.adj[G.per("persona_004")][G.term("pet_food")] == T.graph.edges.affinity


def test_persona_publisher_edges_come_from_audience_fit():
    fit = G.audience_fit(CAT.personas[4], CAT.publisher("pub_005"), T)  # Affluent Classic, Linden Park
    assert fit >= T.graph.audience_min
    assert GR.adj[G.per("persona_005")][G.pub("pub_005")] == round(T.graph.edges.audience * fit, 4)
    gen_z = CAT.personas[2]  # The Gen Z Aesthete, 19-27
    assert G.audience_fit(gen_z, CAT.publisher("pub_005"), T) < T.graph.audience_min
    assert G.pub("pub_005") not in GR.adj[G.per("persona_003")]


# ---- the walk ----

def test_walk_direct_and_two_hop_paths():
    paths = G.walk(GR, {G.term("pet_food"): 1.0}, T.graph)
    best = paths[G.pub("pub_007")][0]
    assert best[1] == (G.term("pet_food"), G.pub("pub_007")) and best[0] == T.graph.edges.subcategory
    tail = paths[G.pub("pub_018")][0]  # Tailcrate has no pet_food: reached through its category
    assert tail[1] == (G.term("pet_food"), G.term("pet"), G.pub("pub_018"))
    g = T.graph  # sub -> category -> publisher, discounted for passing through the category term
    assert abs(tail[0] - g.edges.parent * g.through["term"] * g.edges.primary) < 1e-9


def test_combine_counts_the_best_path_fully_and_corroboration_partly():
    g = T.graph
    assert G.combine([0.7], g) == 0.7
    two = G.combine([0.7, 0.5], g)
    assert 0.7 < two < 1 - 0.3 * 0.5  # less than a plain noisy-or
    assert G.combine([], g) == 0.0


def test_path_text_is_plain_words():
    p = (G.term("home_decor"), G.per("persona_010"), G.pub("pub_014"))
    assert G.path_text(GR, p) == "home decor → The Gifter → Hearthstone Goods"


# ---- scoring through the switch ----

def test_default_impl_is_formula_and_formula_has_no_paths():
    assert T.match.impl == "formula"
    assert all(s.path == [] for s in score_publishers(brief(categories=["pet_food"]), CAT, T))


def _dog_food():
    return brief(categories=["pet_food"], adjacent_categories=["pet_health", "subscription"],
                 price_tier="premium", business_model="subscription")


def test_graph_dog_food_top_two_are_pet_publishers_with_paths():
    s = score_publishers(_dog_food(), CAT, TG)
    top = [p.name for p in s if p.recommended]
    assert set(top[:2]) == {"Pawline", "Ruffco"}
    assert "Velvetline" not in top and "Linden Park" not in top
    for p in s:
        assert [f.name for f in p.factors] == ["category", "audience", "income", "aov"]
        assert p.reason and len(p.reason.split()) <= 8
    paw = _by_name(s)["Pawline"]
    assert paw.path and paw.path[0] == "pet food → Pawline"
    assert len(paw.path) <= T.graph.paths_shown


def test_graph_keeps_the_price_gate_for_luxury():
    s = score_publishers(brief(categories=["apparel"], price_usd=650, price_tier="luxury"), CAT, TG)
    assert is_weak_fit(s, TG)


def test_graph_no_categories_is_weak_fit():
    s = score_publishers(brief(), CAT, TG)
    assert is_weak_fit(s, TG) and all(p.factors[0].score == 0 for p in s)


def test_graph_candles_reach_home_publishers():
    b = brief(product="hand-poured candles", categories=["home_decor"], adjacent_categories=["gifting"],
              price_tier="premium", gender_skew="balanced")
    s = _by_name(score_publishers(b, CAT, TG))
    assert s["Northbed"].recommended and s["Hearthstone Goods"].recommended
    assert s["Hearthstone Goods"].path[0].startswith("home decor → ")


def test_graph_exclude_is_honoured():
    s = _by_name(score_publishers(_dog_food(), CAT, TG, frozenset({"pub_007"})))
    assert not s["Pawline"].recommended


def test_graph_personas_keep_shape_and_get_paths():
    scores = score_personas(_dog_food(), CAT, TG)
    sel = select_personas(scores, TG)
    assert sel[0].name == "The Pet Parent"
    assert sel[0].path and sel[0].path[0] == "pet food → The Pet Parent"
    assert [f.name for f in sel[0].factors][:3] == ["affinity", "price", "age"]


def test_graph_persona_conflict_penalty_still_applies():
    kw = dict(categories=["meal_kits"], price_tier="mid")
    a = next(p for p in score_personas(brief(**kw), CAT, TG) if p.persona_id == "persona_002").fit
    b = next(p for p in score_personas(brief(conflicts=["luxury positioning"], **kw), CAT, TG)
             if p.persona_id == "persona_002").fit
    assert b < a


def test_graph_scoring_is_deterministic():
    assert score_publishers(_dog_food(), CAT, TG) == score_publishers(_dog_food(), CAT, TG)
