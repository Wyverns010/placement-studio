"""Stage 2: one creative per persona (checked by app/copycheck.py, retried once), a rewrite of
one ad (Regenerate), and the clarify questions for stage 1."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from app.catalog import Catalog, Persona
from app.copycheck import (Problem, ad_problems, headline_problems, headlines_similar,
                           normalise_headline)
from app.llm import LLMError, LLMProvider, model_creative, model_fast
from app.models import Brief, ClarifyQuestion, Creative, PersonaScore, PublisherScore
from app.prompts import category_word, feedback, render, wrap_advertiser_text, wrap_current_ad, wrap_user_note
from app.tuning import Tuning


class CreativeItem(BaseModel):
    persona_id: str
    headline: str
    body: str
    cta: str
    why: str


class CreativeBatch(BaseModel):
    items: list[CreativeItem]


class ClarifyBatch(BaseModel):
    questions: list[ClarifyQuestion]


NO_SIGNAL_QUESTIONS: list[ClarifyQuestion] = [
    ClarifyQuestion(
        question="What do you sell?",
        options=["Physical product", "Subscription", "App or service", "Food or drink"],
    ),
    ClarifyQuestion(question="Who usually buys it?", options=["Women", "Men", "Parents", "Everyone"]),
    ClarifyQuestion(question="Roughly what does it cost?", options=["Under $30", "$30–100", "$100+"]),
]

HEADLINE_KINDS = {"headline_duplicate", "headline_product", "headline_unchanged"}


def _pick_publisher(
    persona: Persona, publishers: list[PublisherScore], catalog: Catalog, used: set[str]
) -> PublisherScore | None:
    """Best-overlap recommended publisher, preferring ones not yet `used` by another persona."""
    eligible = [p for p in publishers if p.recommended]
    if not eligible:
        return None
    fresh = [p for p in eligible if p.publisher_id not in used]
    pool = fresh or eligible
    aff = set(persona.category_affinities)
    scored = [(len(catalog.publisher(p.publisher_id).tags & aff), p.fit, p) for p in pool]
    best = max(scored, key=lambda s: (s[0], s[1]))
    if best[0] == 0:
        return max(pool, key=lambda p: p.fit)
    return best[2]


def _persona_block(persona: Persona) -> str:
    return feedback(
        "persona_block",
        id=persona.id, name=persona.name, description=persona.description,
        affinities=", ".join(persona.category_affinities),
        preferences="; ".join(persona.messaging_preferences),
        disinterested="; ".join(persona.disinterested_in),
    )


def _publisher_block(pub: PublisherScore, catalog: Catalog) -> str:
    p = catalog.publisher(pub.publisher_id)
    gender = ", ".join(f"{v:.0%} {k}" for k, v in sorted(p.audience.gender_split.items(),
                                                         key=lambda kv: -kv[1]) if v > 0)
    return feedback(
        "publisher_block",
        name=p.name, category=category_word(p.category),
        age_min=p.age_min, age_max=p.age_max, gender=gender, income=p.audience.income_tier,
        aov=f"{p.avg_order_value_usd:,.0f}", notes=p.notes or feedback("none"),
    )


def _playbook(t: Tuning) -> str:
    return render("copywriting_playbook",
                  banned_phrases=", ".join(f'"{w}"' for w in t.creative.banned_phrases),
                  headline_max=t.creative.headline_max_chars, body_max=t.creative.body_max_chars,
                  cta_max=t.creative.cta_max_chars).strip()


def _flat(s: str, limit: int) -> str:
    """Client-echoed ad text for a prompt: one line, no double quotes, at most `limit` chars."""
    return " ".join(s.replace('"', "").split())[:limit]


def _call_one(text, brief, target, others, catalog, llm, t, violations: list[Problem] | None = None,
              other_headlines: list[str] | None = None,
              rewrite: tuple[Creative, str | None] | None = None):
    """One LLM call for one persona. Returns its CreativeItem, or None if it came back without one.
    `rewrite` = (current ad, optional note) asks for a fresh take on an existing ad."""
    persona, pub = target
    system = render(
        "creative",
        product=brief.product or feedback("product_default"),
        facts="\n".join(f"- {f}" for f in brief.facts) or feedback("facts_default"),
        headline_max=t.creative.headline_max_chars,
        body_max=t.creative.body_max_chars,
        cta_max=t.creative.cta_max_chars,
        personas=_persona_block(persona),
        publisher=_publisher_block(pub, catalog),
        playbook=_playbook(t),
        others="\n".join(
            feedback("other_persona_line", name=o.name,
                     preference=o.messaging_preferences[0] if o.messaging_preferences else feedback("none"))
            for o, _ in others
        )
        or feedback("no_others"),
    )
    user = wrap_advertiser_text(text)
    if rewrite:
        cur, note = rewrite
        c = t.creative
        ad = feedback("current_ad_fields", headline=_flat(cur.headline, c.headline_max_chars),
                      body=_flat(cur.body, c.body_max_chars), cta=_flat(cur.cta, c.cta_max_chars))
        user += feedback("rewrite_current", ad=wrap_current_ad(ad))
        if note:
            user += feedback("rewrite_note", note=wrap_user_note(note))
    if violations:
        user += feedback("retry_preamble", problems="; ".join(v.message for v in violations))
        if other_headlines and any(v.kind in HEADLINE_KINDS for v in violations):
            clean = [_flat(h, t.creative.headline_max_chars) for h in other_headlines]
            user += feedback("other_headlines", headlines=" | ".join(f'"{h}"' for h in clean))
    out = llm.parse(system=system, user=user, schema=CreativeBatch, model=model_creative())
    return next((it for it in out.items if it.persona_id == persona.id), None)


def _call_many(text, brief, targets, all_targets, catalog, llm, t, retry_problems=None, current=None) -> dict[str, CreativeItem]:
    """Concurrent per-persona calls; the first LLMError (or other exception) propagates."""
    retry_problems = retry_problems or {}
    current = current or {}

    def run(target):
        others = [x for x in all_targets if x[0].id != target[0].id]
        heads = [current[o.id] for o, _ in others if o.id in current]
        return _call_one(text, brief, target, others, catalog, llm, t, retry_problems.get(target[0].id), heads)

    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        results = list(pool.map(run, targets))  # input order; re-raises worker exceptions
    return {p.id: it for (p, _), it in zip(targets, results) if it is not None}


def creative_targets(personas: list[PersonaScore], publishers: list[PublisherScore],
                     catalog: Catalog) -> list[tuple[Persona, PublisherScore]]:
    """(persona, publisher) per persona, in order, on distinct recommended publishers where possible."""
    by_id = {p.id: p for p in catalog.personas}
    targets: list[tuple[Persona, PublisherScore]] = []
    used: set[str] = set()
    for ps in personas:
        persona = by_id.get(ps.persona_id)
        pub = _pick_publisher(persona, publishers, catalog, used) if persona else None
        if persona and pub:
            targets.append((persona, pub))
            used.add(pub.publisher_id)
    return targets


def set_problems(creatives: list[Creative], text: str, product: str | None,
                 names: dict[str, str], t: Tuning) -> dict[str, list[Problem]]:
    """Per persona_id: code's problems with each ad (facts, length, generic copy, parroting), then
    headline problems across the set. Also writes them to each creative's fact_violations."""
    probs = {c.persona_id: ad_problems(c, text, names[c.persona_id], t) for c in creatives}
    for pid, vs in headline_problems(creatives, product, names, t.creative.headline_similarity).items():
        probs[pid] += vs
    for c in creatives:
        c.fact_violations = [p.message for p in probs[c.persona_id]]
    return probs


def write_creatives(
    text: str,
    brief: Brief,
    personas: list[PersonaScore],
    publishers: list[PublisherScore],
    catalog: Catalog,
    llm: LLMProvider,
    t: Tuning,
) -> list[Creative]:
    targets = creative_targets(personas, publishers, catalog)
    if not targets:
        return []
    pub_of = {p.id: pub for p, pub in targets}
    names = {p.id: p.name for p, _ in targets}
    result: dict[str, Creative] = {}
    probs: dict[str, list[Problem]] = {}

    def build(it: CreativeItem) -> Creative:
        return Creative(
            creative_id=f"cr_{it.persona_id}",
            persona_id=it.persona_id,
            publisher_id=pub_of[it.persona_id].publisher_id,
            headline=it.headline, body=it.body, cta=it.cta, why=it.why,
        )

    def ordered() -> list[Creative]:
        return [result[p.id] for p, _ in targets if p.id in result]

    def check_all() -> None:
        probs.clear()
        probs.update(set_problems(ordered(), text, brief.product, names, t))

    result.update({pid: build(it) for pid, it in _call_many(text, brief, targets, targets, catalog, llm, t).items()})
    check_all()
    bad = {p.id: probs[p.id] if p.id in result else [Problem("missing", feedback("missing"))]
           for p, _ in targets if p.id not in result or probs[p.id]}
    if bad:
        retry_targets = [(p, pub) for p, pub in targets if p.id in bad]
        current = {pid: r.headline for pid, r in result.items()}
        retried = _call_many(text, brief, retry_targets, targets, catalog, llm, t, retry_problems=bad, current=current)
        result.update({pid: build(it) for pid, it in retried.items()})
        check_all()  # re-check headlines against the final set
    return ordered()


def rewrite_problems(c: Creative, current: Creative, text: str, persona_name: str,
                     product: str | None, other_heads: list[tuple[str, str]],
                     names: dict[str, str], t: Tuning) -> list[Problem]:
    """Code's problems with a rewritten ad: the usual ad checks, plus a headline unchanged from the
    current one, equal to the product name, or like another persona's (`other_heads`: (headline,
    persona_id))."""
    sim = t.creative.headline_similarity
    out = ad_problems(c, text, persona_name, t)
    if headlines_similar(c.headline, current.headline, sim):
        out.append(Problem("headline_unchanged", feedback("headline_unchanged")))
    if normalise_headline(c.headline) == normalise_headline(product or ""):
        out.append(Problem("headline_product", feedback("headline_product")))
    dup = next((pid for h, pid in other_heads if headlines_similar(h, c.headline, sim)), None)
    if dup:
        out.append(Problem("headline_duplicate", feedback("headline_duplicate", name=names.get(dup, dup))))
    return out


def rewrite_creative(
    text: str,
    brief: Brief,
    personas: list[PersonaScore],
    publishers: list[PublisherScore],
    creatives: list[Creative],
    persona_id: str,
    note: str | None,
    catalog: Catalog,
    llm: LLMProvider,
    t: Tuning,
) -> Creative:
    """Rewrite one persona's ad on the same publisher, with the same checks and single retry as
    write_creatives, plus: the headline must differ from the current one and from the others'.
    Raises KeyError for an unknown persona/creative, LLMError if no ad comes back twice."""
    by_id = {p.id: p for p in catalog.personas}
    current = next(c for c in creatives if c.persona_id == persona_id)
    persona = by_id[persona_id]
    pub = next((p for p in publishers if p.publisher_id == current.publisher_id), None)
    if pub is None:
        p = catalog.publisher(current.publisher_id)
        pub = PublisherScore(publisher_id=p.id, name=p.name, fit=0.0, factors=[], recommended=True,
                             stretch=False, reason="")
    others = [(by_id[c.persona_id], pub) for c in creatives
              if c.persona_id != persona_id and c.persona_id in by_id]
    names = {c.persona_id: by_id[c.persona_id].name for c in creatives if c.persona_id in by_id}
    other_heads = [(c.headline, c.persona_id) for c in creatives if c.persona_id != persona_id]

    def build(it: CreativeItem) -> Creative:
        return current.model_copy(update={"headline": it.headline, "body": it.body, "cta": it.cta,
                                          "why": it.why, "fact_violations": []})

    def problems(c: Creative) -> list[Problem]:
        return rewrite_problems(c, current, text, persona.name, brief.product, other_heads, names, t)

    target = (persona, pub)
    heads = [h for h, _ in other_heads]
    it = _call_one(text, brief, target, others, catalog, llm, t, rewrite=(current, note))
    probs = problems(build(it)) if it else [Problem("missing", feedback("missing"))]
    if probs:
        retried = _call_one(text, brief, target, others, catalog, llm, t, probs, heads,
                            rewrite=(current, note))
        it = retried or it
        if it is None:
            raise LLMError("no creative returned for the rewrite")
        probs = problems(build(it))
    out = build(it)
    out.fact_violations = [p.message for p in probs]
    return out


def category_words(catalog: Catalog) -> str:
    cats = sorted({p.category for p in catalog.publishers})
    return ", ".join(category_word(c) for c in cats)


ANSWERS_HEADER = "\n\nAdditional details:\n"  # the API appends clarify answers to the text after this


def answered_questions(text: str) -> dict[str, str]:
    """Clarify answers already in the stage-1 text ("- question: answer" lines after ANSWERS_HEADER)."""
    _, sep, tail = text.partition(ANSWERS_HEADER)
    if not sep:
        return {}
    pairs = (line[2:].split(": ", 1) for line in tail.splitlines() if line.startswith("- "))
    return {p[0].strip(): p[1].strip() for p in pairs if len(p) == 2}


def _norm(q: str) -> str:
    return " ".join(q.lower().replace("?", " ").split())


def clarify_questions(text: str, brief: Brief, llm: LLMProvider, catalog: Catalog,
                      t: Tuning) -> list[ClarifyQuestion]:
    answered = answered_questions(text)
    system = render(
        "clarify",
        categories=category_words(catalog),
        product=brief.product or feedback("product_default"),
        facts="; ".join(brief.facts) or feedback("none"),
        unknowns="\n".join(f"- {u}" for u in brief.unknowns) or feedback("clarify_unknowns_default"),
        answered="\n".join(f"- {q}: {a}" for q, a in answered.items()) or feedback("none"),
    )
    user = wrap_advertiser_text(text)
    out = llm.parse(system=system, user=user, schema=ClarifyBatch, model=model_fast())
    qs: list[ClarifyQuestion] = []
    asked = {_norm(q) for q in answered}
    for q in out.questions:
        if _norm(q.question) in asked:  # the prompt says never re-ask; this catches a verbatim repeat
            continue
        opts = q.options[: t.clarify.max_options]
        if len(opts) >= t.clarify.min_options:
            qs.append(ClarifyQuestion(question=q.question, options=opts))
    return qs[: t.clarify.max_questions]
