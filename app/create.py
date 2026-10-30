"""Stage 4: one creative per persona, a code-enforced facts-only check, and clarify questions."""
from __future__ import annotations

import re

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


def _pick_publisher(persona: Persona, publishers: list[PublisherScore], catalog: Catalog) -> PublisherScore | None:
    eligible = [p for p in publishers if p.recommended]
    if not eligible:
        return None
    aff = set(persona.category_affinities)
    scored = [(len(catalog.publisher(p.publisher_id).tags & aff), p.fit, p) for p in eligible]
    best = max(scored, key=lambda s: (s[0], s[1]))
    if best[0] == 0:
        return max(eligible, key=lambda p: p.fit)
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


def _call(text, brief, targets, catalog, llm, t, feedback: dict[str, list[str]] | None = None):
    system = render(
        "creative",
        product=brief.product or "not stated",
        facts="\n".join(f"- {f}" for f in brief.facts) or "- (no specific facts were extracted)",
        headline_max=t.creative.headline_max_chars,
        body_max=t.creative.body_max_chars,
        cta_max=t.creative.cta_max_chars,
        personas="\n\n".join(_persona_block(p, pub, catalog) for p, pub in targets),
    )
    user = wrap_advertiser_text(text)
    if feedback:
        lines = [
            "Your previous ads broke the rules. Rewrite only the personas below and fix every problem:",
        ]
        for pid, vs in feedback.items():
            lines.append(f"- {pid}: " + "; ".join(vs))
        user += "\n\n" + "\n".join(lines)
    out = llm.parse(system=system, user=user, schema=CreativeBatch, model=model_creative())
    items: dict[str, CreativeItem] = {}
    wanted = {p.id for p, _ in targets}
    for it in out.items:
        if it.persona_id in wanted and it.persona_id not in items:
            items[it.persona_id] = it
    return items


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
    for ps in personas:
        persona = by_id.get(ps.persona_id)
        pub = _pick_publisher(persona, publishers, catalog) if persona else None
        if persona and pub:
            targets.append((persona, pub))
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

    items = _call(text, brief, targets, catalog, llm, t)
    result: dict[str, Creative] = {pid: build(it) for pid, it in items.items()}

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
        for pid, it in _call(text, brief, retry_targets, catalog, llm, t, feedback=bad).items():
            result[pid] = build(it)
    return [result[p.id] for p, _ in targets if p.id in result]


def clarify_questions(text: str, brief: Brief, llm: LLMProvider) -> list[ClarifyQuestion]:
    system = render(
        "clarify",
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
