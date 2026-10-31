"""Stage 4: one creative per persona, a code-enforced facts-only check, and clarify questions."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

from pydantic import BaseModel

from app.catalog import Catalog, Persona
from app.llm import LLMError, LLMProvider, model_creative, model_fast
from app.models import Brief, ClarifyQuestion, Creative, PersonaScore, PublisherScore
from app.prompts import feedback, render, wrap_advertiser_text, wrap_user_note
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


class Problem(NamedTuple):
    """One thing code rejected in an ad; `kind` drives retry behaviour, `message` is the text."""
    kind: str  # fact_number | fact_claim | length | generic_copy | headline_duplicate |
    # headline_product | headline_unchanged | missing
    message: str


_NUMBER = re.compile(r"\$?\d[\d,.]*%?")


def _numbers(text: str) -> set[str]:
    """Digit cores of every number token: $, %, commas and trailing punctuation stripped."""
    return {m.strip("$%").replace(",", "").rstrip(".,") for m in _NUMBER.findall(text)}


def _has_word(word: str, text: str) -> bool:
    return re.search(r"(?<![\w#])" + re.escape(word) + r"(?![\w])", text, re.IGNORECASE) is not None


def check_facts(creative: Creative, input_text: str, t: Tuning) -> list[str]:
    """Violation messages: numbers/claim words absent from the input, and over-length fields."""
    return [p.message for p in fact_problems(creative, input_text, t)]


def fact_problems(creative: Creative, input_text: str, t: Tuning) -> list[Problem]:
    violations: list[Problem] = []
    copy = f"{creative.headline} {creative.body} {creative.cta}"
    known = _numbers(input_text)
    for n in sorted(_numbers(copy)):
        if n not in known:
            violations.append(Problem("fact_number", feedback("fact_number", number=n)))
    for w in t.creative.claim_words:
        if _has_word(w, copy) and not _has_word(w, input_text):
            violations.append(Problem("fact_claim", feedback("fact_claim", word=w)))
    for field, limit in (
        ("headline", t.creative.headline_max_chars),
        ("body", t.creative.body_max_chars),
        ("cta", t.creative.cta_max_chars),
    ):
        n = len(getattr(creative, field))
        if n > limit:
            violations.append(Problem("length", feedback("length", field=field, n=n, limit=limit)))
    return violations


_DASH = r"(?:-|–|—|to)"
# Explicit age context: "ages 25+", "ages 25-34", "ages 25 and up", "aged 30 and over".
_AGE_CONTEXT = re.compile(
    r"\b(?:ages?\s+\d{1,2}|aged\s+\d{2})\s*(?:\+|and\s+(?:up|over|older)\b|" + _DASH + r"\s*\d{1,2}\b)",
    re.IGNORECASE)
# A bare two-number range ("18-24"); only an age when both ends are plausible ages and no unit
# follows ("24-48 hours", "20-30 oz", "20-30%"). "25-34 year olds" is still an age.
_UNITS = (r"(?:%|(?:percent|hours?|hrs?|days?|nights?|minutes?|mins?|seconds?|secs?|weeks?|months?"
          r"|years?(?![\s-]*olds?)|yrs?|oz|ml|l|liters?|litres?|lbs?|pounds?|kg|g|grams?|cm|mm|in"
          r"|inch(?:es)?|ft|feet|servings?|packs?|pieces?|pcs|count|ct|calories|cal|mg)\b)")
_BARE_RANGE = re.compile(r"\b(\d{2})\s*" + _DASH + r"\s*(\d{2})\b(?!\s*" + _UNITS + ")", re.IGNORECASE)
_UNDER = re.compile(r"\bunder\s+\$\s?\d[\d,]*", re.IGNORECASE)


def _plain(text: str) -> str:
    """Lowercase, dashes unified ("25 to 34" -> "25-34") and whitespace collapsed, for 'did the
    advertiser write it'."""
    text = re.sub(r"(\d)\s*(?:–|—|-|\bto\b)\s*(\d)", r"\1-\2", text.lower())
    text = re.sub(r"\s*[–—-]\s*", "-", text)
    return " ".join(text.split())


def _in_source(phrase: str, source: str) -> bool:
    """Whole-word containment ('for men' is not inside 'for mental')."""
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", source) is not None


def _phrase_pattern(phrase: str) -> re.Pattern:
    """A banned phrase with space/hyphen variants and simple inflections of its last word
    ("elevate" -> elevates/elevated/elevating; "high-quality" -> "high quality")."""
    words = re.split(r"[\s-]+", phrase.strip().lower())
    *head, last = words
    if last.endswith("e"):
        tail = re.escape(last[:-1]) + r"(?:e|es|ed|ing)"
    elif last.isalpha():
        tail = re.escape(last) + r"(?:s|es|ed|ing)?"
    else:
        tail = re.escape(last)
    body = r"[\s-]+".join([re.escape(w) for w in head] + [tail])
    return re.compile(r"(?<![\w#])" + body + r"(?!\w)", re.IGNORECASE)


def _is_age_range(m: re.Match, t: Tuning) -> bool:
    lo, hi = t.creative.age_range_bounds
    return all(lo <= int(g) <= hi for g in m.groups())


def generic_problems(creative: Creative, input_text: str, t: Tuning) -> list[Problem]:
    """Headline/body copy that restates targeting (age ranges, "for women"), uses a price band
    ("under $50") or a banned filler phrase. Anything the advertiser wrote themselves is allowed."""
    copy = f"{creative.headline} {creative.body}"
    source = _plain(input_text)
    audience = re.compile(r"\bfor\s+(?:" + "|".join(re.escape(w) for w in t.creative.audience_words)
                          + r")(?![\w'’])", re.IGNORECASE)
    out: list[Problem] = []
    found: list[tuple[str, str]] = []  # (feedback key, phrase as written)
    found += [("generic_age", m.group(0)) for m in _AGE_CONTEXT.finditer(copy)]
    found += [("generic_age", m.group(0)) for m in _BARE_RANGE.finditer(copy)
              if _is_age_range(m, t) and not any(m.start() >= a.start() and m.end() <= a.end()
                                                 for a in _AGE_CONTEXT.finditer(copy))]
    found += [("generic_audience", m.group(0)) for m in audience.finditer(copy)]
    found += [("generic_price_band", m.group(0)) for m in _UNDER.finditer(copy)]
    for key, phrase in found:
        p = _plain(phrase)
        if not _in_source(p, source):
            out.append(Problem("generic_copy", feedback(key, phrase=p)))
    for w in t.creative.banned_phrases:
        pat = _phrase_pattern(w)
        if pat.search(copy) and not pat.search(input_text):
            out.append(Problem("generic_copy", feedback("generic_phrase", phrase=w)))
    return out


def ad_problems(creative: Creative, input_text: str, t: Tuning) -> list[Problem]:
    """Everything code checks on one ad: facts, lengths and generic copy."""
    return fact_problems(creative, input_text, t) + generic_problems(creative, input_text, t)


def normalise_headline(text: str) -> str:
    """Lowercase with punctuation and whitespace removed, for duplicate checks."""
    return re.sub(r"[\W_]+", "", text.lower())


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def headline_similarity(a: str, b: str) -> float:
    """Token-set Jaccard of two headlines' lowercase words (1.0 = same words)."""
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 1.0


def headlines_similar(a: str, b: str, threshold: float) -> bool:
    return normalise_headline(a) == normalise_headline(b) or headline_similarity(a, b) >= threshold


def headline_problems(creatives: list[Creative], product: str | None,
                      names: dict[str, str], threshold: float = 1.0) -> dict[str, list[Problem]]:
    """Per persona_id: a headline that repeats an earlier persona's (in order) or is just the
    product name. `names` maps persona_id -> display name."""
    out: dict[str, list[Problem]] = {}
    seen: list[tuple[str, str]] = []  # (headline, persona_id)
    prod = normalise_headline(product or "")
    for c in creatives:
        h = normalise_headline(c.headline)
        if prod and h == prod:
            out.setdefault(c.persona_id, []).append(Problem("headline_product", feedback("headline_product")))
        else:
            dup = next((pid for hl, pid in seen if headlines_similar(hl, c.headline, threshold)), None)
            if dup:
                out.setdefault(c.persona_id, []).append(
                    Problem("headline_duplicate", feedback("headline_duplicate", name=names.get(dup, dup))))
            else:
                seen.append((c.headline, c.persona_id))
    return out


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
        name=p.name, category=_CATEGORY_WORDS.get(p.category, p.category.replace("_", " ")),
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
        user += feedback("rewrite_current", headline=_flat(cur.headline, c.headline_max_chars),
                         body=_flat(cur.body, c.body_max_chars), cta=_flat(cur.cta, c.cta_max_chars))
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
        """Fact/length problems per creative, then headline problems across the whole set."""
        probs.clear()
        probs.update({pid: ad_problems(c, text, t) for pid, c in result.items()})
        for pid, vs in headline_problems(ordered(), brief.product, names, t.creative.headline_similarity).items():
            probs[pid] += vs
        for pid, c in result.items():
            c.fact_violations = [p.message for p in probs[pid]]

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
    sim = t.creative.headline_similarity

    def build(it: CreativeItem) -> Creative:
        return current.model_copy(update={"headline": it.headline, "body": it.body, "cta": it.cta,
                                          "why": it.why, "fact_violations": []})

    def problems(c: Creative) -> list[Problem]:
        out = ad_problems(c, text, t)
        if headlines_similar(c.headline, current.headline, sim):
            out.append(Problem("headline_unchanged", feedback("headline_unchanged")))
        if normalise_headline(c.headline) == normalise_headline(brief.product or ""):
            out.append(Problem("headline_product", feedback("headline_product")))
        dup = next((pid for h, pid in other_heads if headlines_similar(h, c.headline, sim)), None)
        if dup:
            out.append(Problem("headline_duplicate",
                               feedback("headline_duplicate", name=names.get(dup, dup))))
        return out

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
        product=brief.product or feedback("product_default"),
        facts="; ".join(brief.facts) or feedback("none"),
        unknowns="\n".join(f"- {u}" for u in brief.unknowns) or feedback("clarify_unknowns_default"),
    )
    user = wrap_advertiser_text(text)
    out = llm.parse(system=system, user=user, schema=ClarifyBatch, model=model_fast())
    qs: list[ClarifyQuestion] = []
    for q in out.questions:
        opts = q.options[:5]
        if len(opts) >= 2:
            qs.append(ClarifyQuestion(question=q.question, options=opts))
    return qs[:3]
