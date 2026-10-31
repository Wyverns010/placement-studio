"""Shopper-graph matching (match.impl: graph): the category factor becomes graph proximity.

The graph is built from the data pack only. Nodes are category terms, publishers and personas;
edges (undirected, weights in config/tuning.yaml `graph.edges`):

  publisher - its category (primary), its subcategories (subcategory; attribute tags: attribute)
  subcategory - the category it sits under in the catalog, interest term - its affinity_parents
      category (parent)
  persona - each category affinity (affinity)
  persona - publisher when their audience fit (the persona read as a brief, scored by the same
      age/gender and income factors a brief gets) is at least `audience_min` (audience x fit)

Scoring walks every simple path of up to `max_hops` edges from the brief's categories (seed
weight `seed.category`) and adjacent categories (`seed.adjacent`). A path's weight is its seed
weight times its edge weights times `through[kind]` for each node it passes through (a persona or
publisher in the middle of a path is a co-shopper hop, discounted like a PageRank damping step), so a direct match keeps the formula's level (pet_food -> Pawline
= 0.85) and each extra hop discounts it (pet_food -> pet -> Tailcrate = 0.7). A node's graph
score combines its `paths_combined` strongest paths: the best counts fully, the rest as
corroboration, 1 - (1-w1) * prod(1 - corroboration * wk). The same paths explain the pick.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.catalog import Catalog, Persona, Publisher
from app.models import Brief, Factor
from app.tuning import GraphTuning, Tuning

Path = tuple[str, ...]


def term(v: str) -> str:
    return f"t:{v}"


def pub(pid: str) -> str:
    return f"pub:{pid}"


def per(pid: str) -> str:
    return f"per:{pid}"


def kind(node: str) -> str:
    return {"t": "term", "pub": "publisher", "per": "persona"}[node.split(":", 1)[0]]


@dataclass(frozen=True)
class Graph:
    adj: dict[str, dict[str, float]]  # node -> neighbour -> weight (both directions stored)
    label: dict[str, str]  # node -> plain words


def _persona_brief(q: Persona, t: Tuning) -> Brief:
    """A persona read as a brief, so the publisher audience/income factors can score the pair.
    Its price tier is the one whose persona price ideal (tuning persona.price_ideal) is nearest."""
    ideal = t.persona.price_ideal
    tier = min(ideal, key=lambda k: abs(ideal[k] - q.price_rank))
    gender = {"female": "female", "female-leaning": "female", "male": "male",
              "male-leaning": "male"}.get(q.gender_skew, "balanced")
    return Brief(describes_business=True, product=None, audience_type="consumer", categories=[],
                 adjacent_categories=[], conflicts=[], price_usd=None, price_tier=tier,
                 business_model="unknown", age_min=q.age_min, age_max=q.age_max,
                 gender_skew=gender, facts=[], unknowns=[], self_confidence=1.0)


def audience_fit(q: Persona, p: Publisher, t: Tuning) -> float:
    """Persona-publisher audience fit in [0, 1]: the publisher audience and income factors for the
    persona-as-brief, weighted as the formula weights them."""
    from app.match import _audience, _income

    b = _persona_brief(q, t)
    w = t.publisher.weights
    aud, _ = _audience(b, p, t)
    inc, _ = _income(b, p, t)
    return (w.audience * aud.score + w.income * inc.score) / (w.audience + w.income)


def build_graph(catalog: Catalog, t: Tuning) -> Graph:
    e = t.graph.edges
    attrs = set(t.publisher.attribute_tags)
    adj: dict[str, dict[str, float]] = defaultdict(dict)
    label: dict[str, str] = {}

    def add(a: str, b: str, w: float) -> None:
        w = round(w, 4)
        if w > adj[a].get(b, 0.0):
            adj[a][b] = adj[b][a] = w

    for v in catalog.vocab:
        label[term(v)] = v.replace("_", " ")
        adj[term(v)]  # every vocab term is a node, even an isolated one
    for p in catalog.publishers:
        label[pub(p.id)] = p.name
        add(pub(p.id), term(p.category), e.primary)
        for s in p.subcategories:
            add(pub(p.id), term(s), e.attribute if s in attrs else e.subcategory)
    for cat, subs in catalog.vocab_groups().items():
        for s in subs:
            if s not in attrs and s != cat:
                add(term(s), term(cat), e.parent)
    for v, parent in t.publisher.affinity_parents.items():
        add(term(v), term(parent), e.parent)
    for q in catalog.personas:
        label[per(q.id)] = q.name
        adj[per(q.id)]
        for a in q.category_affinities:
            add(per(q.id), term(a), e.attribute if a in attrs else e.affinity)
        for p in catalog.publishers:
            fit = audience_fit(q, p, t)
            if fit >= t.graph.audience_min:
                add(per(q.id), pub(p.id), e.audience * fit)
    return Graph(adj=dict(adj), label=label)


def seeds(b: Brief, t: Tuning) -> dict[str, float]:
    s = t.graph.seed
    out = {term(c): s.adjacent for c in b.adjacent_categories}
    out.update({term(c): s.category for c in b.categories})
    return out


def walk(g: Graph, start: dict[str, float], gt: GraphTuning) -> dict[str, list[tuple[float, Path]]]:
    """Every simple path of 1..max_hops edges from a seed, weight = seed x edge weights x the
    pass-through multiplier of each inner node (paths under min_path_weight are pruned), per end
    node, strongest first."""
    out: dict[str, list[tuple[float, Path]]] = defaultdict(list)

    def go(path: Path, w: float) -> None:
        here = path[-1]
        hop = gt.through[kind(here)] if len(path) > 1 else 1.0  # passing through, not starting
        for nb, ew in g.adj[here].items():
            nw = w * hop * ew
            if nb in path or nw < gt.min_path_weight:
                continue
            p = path + (nb,)
            out[nb].append((nw, p))
            if len(p) - 1 < gt.max_hops:
                go(p, nw)

    for s, w in sorted(start.items()):
        if s in g.adj:
            go((s,), w)
    for v in out.values():
        v.sort(key=lambda x: (-x[0], x[1]))
    return out


def combine(weights: list[float], gt: GraphTuning) -> float:
    """Strongest path counts fully; the next ones corroborate at `corroboration` share."""
    ws = sorted(weights, reverse=True)[: gt.paths_combined]
    if not ws:
        return 0.0
    miss = 1 - min(1.0, ws[0])
    for w in ws[1:]:
        miss *= 1 - gt.corroboration * min(1.0, w)
    return round(1 - miss, 4)


def path_text(g: Graph, p: Path) -> str:
    return " → ".join(g.label.get(n, n) for n in p)


def _note(g: Graph, p: Path, direct: str) -> str:
    if len(p) == 2:
        return f"{direct}: {g.label[p[0]]}"
    return f"Via {g.label[p[1]]}"


def _scored(g: Graph, paths: dict[str, list[tuple[float, Path]]], node: str, t: Tuning,
            direct: str, name: str) -> tuple[Factor, list[str]]:
    ps = paths.get(node, [])
    score = combine([w for w, _ in ps], t.graph)
    if not ps:
        return Factor(name=name, score=0.0, note="No graph path"), []
    shown = [path_text(g, p) for _, p in ps[: t.graph.paths_shown]]
    return Factor(name=name, score=score, note=_note(g, ps[0][1], direct)), shown


def publisher_category(b: Brief, catalog: Catalog, t: Tuning) -> dict[str, tuple[Factor, str, list[str]]]:
    """publisher id -> (category factor = graph score, level, path texts). Level "none" (graph
    score under penalty_below) gets the formula's no_category_penalty."""
    g = build_graph(catalog, t)
    paths = walk(g, seeds(b, t), t.graph)
    out = {}
    for p in catalog.publishers:
        f, shown = _scored(g, paths, pub(p.id), t, "Linked", "category")
        out[p.id] = (f, "none" if f.score < t.graph.penalty_below else "graph", shown)
    return out


def persona_affinity(b: Brief, catalog: Catalog, t: Tuning) -> dict[str, tuple[Factor, list[str]]]:
    """persona id -> (affinity factor = graph score, path texts)."""
    g = build_graph(catalog, t)
    paths = walk(g, seeds(b, t), t.graph)
    return {q.id: _scored(g, paths, per(q.id), t, "Affinity", "affinity") for q in catalog.personas}
