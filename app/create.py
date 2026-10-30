"""Stage 4: one creative per persona, a code-enforced facts-only check, and clarify questions."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from app.catalog import Catalog, Persona
from app.llm import LLMProvider, model_creative, model_fast
from app.models import Brief, ClarifyQuestion, Creative, PersonaScore, PublisherScore
from app.prompts import render, wrap_advertiser_text
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

MISSING = "missing creative"
_NUMBER = re.compile(r"\$?\d[\d,.]*%?")


def _numbers(text: str) -> set[str]:
    """Digit cores of every number token: $, %, commas and trailing punctuation stripped."""
    return {m.strip("$%").replace(",", "").rstrip(".,") for m in _NUMBER.findall(text)}


def _has_word(word: str, text: str) -> bool:
    return re.search(r"(?<![\w#])" + re.escape(word) + r"(?![\w])", text, re.IGNORECASE) is not None


def check_facts(creative: Creative, input_text: str, t: Tuning) -> list[str]:
    """Violations: numbers/claim words absent from the input, and over-length fields."""
    violations: list[str] = []
    copy = f"{creative.headline} {creative.body} {creative.cta}"
    known = _numbers(input_text)
    for n in sorted(_numbers(copy)):
        if n not in known:
            violations.append(f"number '{n}' is not in the advertiser's text")
    for w in t.creative.claim_words:
        if _has_word(w, copy) and not _has_word(w, input_text):
            violations.append(f"claim '{w}' is not in the advertiser's text")
    for field, limit in (
        ("headline", t.creative.headline_max_chars),
        ("body", t.creative.body_max_chars),
        ("cta", t.creative.cta_max_chars),
    ):
        n = len(getattr(creative, field))
        if n > limit:
            violations.append(f"{field} is {n} characters; the limit is {limit}")
    return violations


def normalise_headline(text: str) -> str:
    """Lowercase with punctuation and whitespace removed, for duplicate checks."""
    return re.sub(r"[\W_]+", "", text.lower())


def headline_problems(creatives: list[Creative], product: str | None,
                      names: dict[str, str]) -> dict[str, list[str]]:
    """Per persona_id: a headline that repeats an earlier persona's (in order) or is just the
    product name. `names` maps persona_id -> display name."""
    out: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    prod = normalise_headline(product or "")
    for c in creatives:
        h = normalise_headline(c.headline)
        if prod and h == prod:
            out.setdefault(c.persona_id, []).append("headline is just the product name")
        elif h in seen:
            out.setdefault(c.persona_id, []).append(
                f"headline duplicates {names.get(seen[h], seen[h])}'s — write a different one")
        else:
            seen[h] = c.persona_id
    return out


def _pick_publisher(
    persona: Persona, publishers: list[PublisherScore], catalog: Catalog, used: set[str] | None = None
) -> PublisherScore | None:
    """Best-overlap recommended publisher, preferring ones not yet `used` by another persona."""
    eligible = [p for p in publishers if p.recommended]
    if not eligible:
        return None
    fresh = [p for p in eligible if p.publisher_id not in (used or set())]
    pool = fresh or eligible
    aff = set(persona.category_affinities)
    scored = [(len(catalog.publisher(p.publisher_id).tags & aff), p.fit, p) for p in pool]
    best = max(scored, key=lambda s: (s[0], s[1]))
    if best[0] == 0:
        return max(pool, key=lambda p: p.fit)
    return best[2]


def _persona_block(persona: Persona, pub: PublisherScore, catalog: Catalog) -> str:
    notes = catalog.publisher(pub.publisher_id).notes or "none"
    return (
        f"## persona_id: {persona.id} ({persona.name})\n"
        f"Description: {persona.description}\n"
        f"Category affinities: {', '.join(persona.category_affinities)}\n"
        f"Messaging preferences: {'; '.join(persona.messaging_preferences)}\n"
        f"Disinterested in: {'; '.join(persona.disinterested_in)}\n"
        f"Publisher: {pub.name}. Notes: {notes}"
    )


def _call_one(text, brief, target, others, catalog, llm, t, violations: list[str] | None = None):
    """One LLM call for one persona. Returns its CreativeItem, or None if it came back without one."""
    persona, pub = target
    system = render(
        "creative",
        product=brief.product or "not stated",
        facts="\n".join(f"- {f}" for f in brief.facts) or "- (no specific facts were extracted)",
        headline_max=t.creative.headline_max_chars,
        body_max=t.creative.body_max_chars,
        cta_max=t.creative.cta_max_chars,
        personas=_persona_block(persona, pub, catalog),
        others="\n".join(
            f"- {o.name}: top messaging preference: {o.messaging_preferences[0] if o.messaging_preferences else 'none'}"
            for o, _ in others
        )
        or "- (none; this is the only persona)",
    )
    user = wrap_advertiser_text(text)
    if violations:
        user += (
            "\n\nYour previous ad broke the rules. Rewrite it and fix every problem: "
            + "; ".join(violations)
        )
    out = llm.parse(system=system, user=user, schema=CreativeBatch, model=model_creative())
    return next((it for it in out.items if it.persona_id == persona.id), None)


def _call_many(text, brief, targets, all_targets, catalog, llm, t, feedback=None) -> dict[str, CreativeItem]:
    """Concurrent per-persona calls; the first LLMError (or other exception) propagates."""
    feedback = feedback or {}

    def run(target):
        others = [x for x in all_targets if x[0].id != target[0].id]
        return _call_one(text, brief, target, others, catalog, llm, t, feedback.get(target[0].id))

    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        results = list(pool.map(run, targets))  # input order; re-raises worker exceptions
    return {p.id: it for (p, _), it in zip(targets, results) if it is not None}


def write_creatives(
    text: str,
    brief: Brief,
    personas: list[PersonaScore],
    publishers: list[PublisherScore],
    catalog: Catalog,
    llm: LLMProvider,
    t: Tuning,
) -> list[Creative]:
    by_id = {p.id: p for p in catalog.personas}
    targets: list[tuple[Persona, PublisherScore]] = []
    used: set[str] = set()
    for ps in personas:
        persona = by_id.get(ps.persona_id)
        pub = _pick_publisher(persona, publishers, catalog, used) if persona else None
        if persona and pub:
            targets.append((persona, pub))
            used.add(pub.publisher_id)
    if not targets:
        return []
    pub_of = {p.id: pub for p, pub in targets}

    def build(it: CreativeItem) -> Creative:
        c = Creative(
            creative_id=f"cr_{it.persona_id}",
            persona_id=it.persona_id,
            publisher_id=pub_of[it.persona_id].publisher_id,
            headline=it.headline, body=it.body, cta=it.cta, why=it.why,
        )
        c.fact_violations = check_facts(c, text, t)
        return c

    items = _call_many(text, brief, targets, targets, catalog, llm, t)
    result: dict[str, Creative] = {pid: build(it) for pid, it in items.items()}
    names = {p.id: p.name for p, _ in targets}

    def ordered() -> list[Creative]:
        return [result[p.id] for p, _ in targets if p.id in result]

    def add_headline_problems() -> None:
        for pid, vs in headline_problems(ordered(), brief.product, names).items():
            result[pid].fact_violations = result[pid].fact_violations + vs

    add_headline_problems()

    def problems() -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for p, _ in targets:
            c = result.get(p.id)
            if c is None:
                out[p.id] = [MISSING]
            elif c.fact_violations:
                out[p.id] = list(c.fact_violations)
        return out

    bad = problems()
    if bad:
        retry_targets = [(p, pub) for p, pub in targets if p.id in bad]
        for pid, it in _call_many(text, brief, retry_targets, targets, catalog, llm, t, feedback=bad).items():
            result[pid] = build(it)
        for c in result.values():  # re-check headlines against the final set
            c.fact_violations = check_facts(c, text, t)
        add_headline_problems()
    return ordered()


_CATEGORY_WORDS = {
    "pet": "pet", "apparel": "apparel", "home": "home goods", "beauty": "beauty",
    "groceries": "groceries", "meal_kits": "meal kits", "beverages": "drinks",
    "wellness_dtc": "wellness products", "wellness_services": "fitness/wellness services",
    "instant_delivery": "instant delivery",
}


def category_words(catalog: Catalog) -> str:
    cats = sorted({p.category for p in catalog.publishers})
    return ", ".join(_CATEGORY_WORDS.get(c, c.replace("_", " ")) for c in cats)


def clarify_questions(text: str, brief: Brief, llm: LLMProvider, catalog: Catalog) -> list[ClarifyQuestion]:
    system = render(
        "clarify",
        categories=category_words(catalog),
        product=brief.product or "not stated",
        facts="; ".join(brief.facts) or "none",
        unknowns="\n".join(f"- {u}" for u in brief.unknowns) or "- what the business sells, who buys it, price",
    )
    user = wrap_advertiser_text(text)
    out = llm.parse(system=system, user=user, schema=ClarifyBatch, model=model_fast())
    qs: list[ClarifyQuestion] = []
    for q in out.questions:
        opts = q.options[:5]
        if len(opts) >= 2:
            qs.append(ClarifyQuestion(question=q.question, options=opts))
    return qs[:3]
