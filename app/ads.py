"""Step 3: one ad per persona. Each ad is written, checked by code, reviewed by the Critic when code
found it clean, revised once if anything needs fixing, then checked again: what's still wrong
ships flagged."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from app.constants.ads import CTA_OPTIONS, NUMBER
from app.constants.llm import MODEL_CREATIVE, MODEL_FAST
from app.llm import LLMError, LLMProvider
from app.models.ads import Creative, Draft, Review
from app.models.brief import Brief
from app.models.catalog import Catalog, Persona, Publisher
from app.models.scores import PersonaScore, PublisherScore
from app.models.tuning import Tuning
from app.prompts import CATEGORY_WORDS, FEEDBACK, render, wrap

log = logging.getLogger(__name__)

# ---- checks ----

def fact_problems(ad: Draft | Creative, text: str, tuning: Tuning) -> list[str]:
    """What code never lets through: numbers or claim words the advertiser didn't write, and
    over-long fields."""
    copy = f"{ad.headline} {ad.body} {ad.cta}"
    written = {match.strip("$%").replace(",", "").rstrip(".,") for match in NUMBER.findall(text)}
    used = {match.strip("$%").replace(",", "").rstrip(".,") for match in NUMBER.findall(copy)}
    problems = [FEEDBACK["fact_number"].format(number=number) for number in sorted(used - written)]
    for word in tuning.creative.claim_words:
        claim = re.compile(r"(?<![\w#])" + re.escape(word) + r"(?![\w])", re.IGNORECASE)
        if claim.search(copy) and not claim.search(text):
            problems.append(FEEDBACK["fact_claim"].format(word=word))
    limits = tuning.creative
    for field, limit in (("headline", limits.headline_max_chars), ("body", limits.body_max_chars),
                         ("cta", limits.cta_max_chars)):
        length = len(getattr(ad, field))
        if length > limit:
            problems.append(FEEDBACK["length"].format(field=field, n=length, limit=limit))
    return problems


def normalise_headline(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


def _same_headline(first: str, second: str, threshold: float) -> bool:
    """Equal once normalised, or sharing at least `threshold` of their words (Jaccard)."""
    if normalise_headline(first) == normalise_headline(second):
        return True
    words_a, words_b = set(re.findall(r"\w+", first.lower())), set(re.findall(r"\w+", second.lower()))
    overlap = len(words_a & words_b) / len(words_a | words_b) if words_a | words_b else 1.0
    return overlap >= threshold


def flag_duplicate_headlines(ads: list[Creative], product: str | None, names: dict[str, str],
                             tuning: Tuning) -> None:
    """Flag an ad whose headline is just the product name, or repeats an earlier ad's."""
    product_headline = normalise_headline(product or "")
    seen: list[Creative] = []
    for ad in ads:
        if product_headline and normalise_headline(ad.headline) == product_headline:
            ad.fact_violations.append(FEEDBACK["headline_product"])
            continue
        earlier = next((other for other in seen
                        if _same_headline(other.headline, ad.headline, tuning.creative.headline_similarity)), None)
        if earlier:
            ad.fact_violations.append(FEEDBACK["headline_duplicate"].format(name=names[earlier.persona_id]))
        else:
            seen.append(ad)


# ---- writing ----

def ad_slots(persona_scores: list[PersonaScore], publisher_scores: list[PublisherScore],
             catalog: Catalog) -> list[tuple[Persona, Publisher]]:
    """One publisher per persona: the recommended one sharing most of its categories, preferring
    publishers not used yet; with no overlap, the best fit."""
    recommended = [score for score in publisher_scores if score.recommended]
    slots, used = [], set()
    for persona_score in persona_scores:
        if not recommended:
            break
        persona = catalog.persona_by_id[persona_score.persona_id]
        pool = [score for score in recommended if score.publisher_id not in used] or recommended
        affinities = set(persona.category_affinities)
        overlap = {score.publisher_id: len(catalog.publisher_by_id[score.publisher_id].tags & affinities)
                   for score in pool}
        best = max(pool, key=lambda score: (overlap[score.publisher_id], score.fit))
        if overlap[best.publisher_id] == 0:
            best = max(pool, key=lambda score: score.fit)
        slots.append((persona, catalog.publisher_by_id[best.publisher_id]))
        used.add(best.publisher_id)
    return slots


def _persona_text(persona: Persona) -> str:
    return FEEDBACK["persona_block"].format(
        id=persona.id, name=persona.name, description=persona.description,
        affinities=", ".join(persona.category_affinities), preferences="; ".join(persona.messaging_preferences),
        disinterested="; ".join(persona.disinterested_in))


def _publisher_text(publisher: Publisher) -> str:
    split = sorted(publisher.audience.gender_split.items(), key=lambda item: -item[1])
    return FEEDBACK["publisher_block"].format(
        name=publisher.name, category=CATEGORY_WORDS.get(publisher.category, publisher.category.replace("_", " ")),
        age_min=publisher.age_min, age_max=publisher.age_max,
        gender=", ".join(f"{share:.0%} {gender}" for gender, share in split if share > 0),
        income=publisher.audience.income_tier, aov=f"{publisher.avg_order_value_usd:,.0f}",
        notes=publisher.notes or FEEDBACK["none"])


def _playbook(tuning: Tuning) -> str:
    limits = tuning.creative
    return render("copywriting_playbook", banned_phrases=", ".join(f'"{phrase}"' for phrase in limits.banned_phrases),
                  headline_max=limits.headline_max_chars, body_max=limits.body_max_chars,
                  cta_max=limits.cta_max_chars, ctas=", ".join(f'"{cta}"' for cta in CTA_OPTIONS)).strip()


def write_ad(persona: Persona, publisher: Publisher, others: list[Persona], text: str, brief: Brief,
             note: str | None, llm: LLMProvider, tuning: Tuning) -> Creative | None:
    """Write -> code checks -> Critic (only if code found it clean) -> one revision if anything needs
    fixing -> final code check. A failed Critic call counts as accepted, a failed revision ships the
    first draft flagged, and a failed first draft means no ad for this persona (None)."""
    playbook = _playbook(tuning)
    system = render(
        "copywriter",
        product=brief.product or FEEDBACK["product_default"],
        facts="\n".join(f"- {fact}" for fact in brief.facts) or FEEDBACK["facts_default"],
        headline_max=tuning.creative.headline_max_chars, body_max=tuning.creative.body_max_chars,
        persona=_persona_text(persona), publisher=_publisher_text(publisher), playbook=playbook,
        others="\n".join(FEEDBACK["other_persona_line"].format(
            name=other.name, preference=(other.messaging_preferences or [FEEDBACK["none"]])[0])
            for other in others) or FEEDBACK["no_others"],
    )
    user = wrap("advertiser_text", text) + ("\n" + wrap("user_note", note) if note else "")
    try:
        draft = llm.parse(system=system, user=user, schema=Draft, model=MODEL_CREATIVE)
    except LLMError as error:
        log.warning("no ad for %s: %s", persona.id, error)
        return None
    fixes = fact_problems(draft, text, tuning)
    if not fixes:
        try:
            review = llm.parse(system=render("critic", persona=_persona_text(persona),
                                             publisher=_publisher_text(publisher), playbook=playbook),
                               user=draft.model_dump_json(), schema=Review, model=MODEL_FAST)
            fixes = [] if review.accept else review.notes
        except LLMError:
            fixes = []
    if fixes:
        retry = FEEDBACK["fix"].format(draft=draft.model_dump_json(), problems="; ".join(fixes))
        try:
            draft = llm.parse(system=system, user=user + retry, schema=Draft, model=MODEL_CREATIVE)
        except LLMError as error:
            log.warning("revision failed for %s, shipping the first draft: %s", persona.id, error)
    return Creative(persona_id=persona.id, publisher_id=publisher.id, **draft.model_dump(),
                    fact_violations=fact_problems(draft, text, tuning))


def write_ads(text: str, brief: Brief, publisher_scores: list[PublisherScore], persona_scores: list[PersonaScore],
              note: str | None, llm: LLMProvider, catalog: Catalog, tuning: Tuning) -> list[Creative]:
    """Every persona's ad at the same time (each is an independent ~4-8 s call), then the duplicate
    headline check across them. A persona whose ad couldn't be written is left out."""
    slots = ad_slots(persona_scores, publisher_scores, catalog)
    personas = [persona for persona, _ in slots]
    with ThreadPoolExecutor(max_workers=max(1, len(slots))) as pool:
        written = list(pool.map(lambda slot: write_ad(
            slot[0], slot[1], [other for other in personas if other.id != slot[0].id], text, brief, note, llm,
            tuning), slots))
    ads = [ad for ad in written if ad]
    flag_duplicate_headlines(ads, brief.product, {persona.id: persona.name for persona in personas}, tuning)
    return ads
