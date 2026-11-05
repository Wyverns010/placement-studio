"""Step 1: read the advertiser's text into a brief, decide the outcome, ask clarify questions, and
apply a note."""
from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, create_model

from app.constants.brief import (
    ANSWERS_HEADER,
    CLARIFY_TOPICS,
    NOTE_ADDED,
    NOTE_AGES,
    NOTE_AGES_REFUSED,
    NOTE_DROPPED,
    NOTE_NOT_NAMED,
    NOTE_NOT_READ,
    NOTE_REMOVED,
)
from app.constants.llm import MODEL_FAST
from app.llm import LLMError, LLMProvider
from app.models.brief import (
    Brief,
    BriefChanges,
    ClarifyBatch,
    ClarifyQuestion,
    GateResult,
)
from app.models.catalog import Catalog
from app.models.tuning import GateTuning, Tuning
from app.prompts import CATEGORY_WORDS, FEEDBACK, render, wrap

_SCHEMAS: dict[tuple[str, ...], type[BaseModel]] = {}


def brief_schema(catalog: Catalog) -> type[BaseModel]:
    """Brief with its category fields limited to the catalog's words, every field required (strict
    structured output); built once per vocabulary."""
    key = (*catalog.vocab, "|", *catalog.conflict_vocab)
    if key not in _SCHEMAS:
        fields = {name: (field.annotation, ...) for name, field in Brief.model_fields.items()}
        fields["categories"] = fields["adjacent_categories"] = (list[Literal[tuple(catalog.vocab)]], ...)
        fields["conflicts"] = (list[Literal[tuple(catalog.conflict_vocab)]], ...)
        _SCHEMAS[key] = create_model("BriefSchema", **fields)
    return _SCHEMAS[key]


def understand(text: str, catalog: Catalog, llm: LLMProvider, tuning: Tuning) -> Brief:
    """One LLM call reads the text; code then keeps the buyer's ages, unique categories and a real price."""
    system = render(
        "understand",
        category_vocab="\n".join(f"- {category}: {', '.join(words)}"
                                 for category, words in catalog.vocab_groups.items()),
        interest_vocab=", ".join(catalog.interest_terms),
        conflict_vocab=", ".join(catalog.conflict_vocab),
    )
    reply = llm.parse(system=system, user=wrap("advertiser_text", text), schema=brief_schema(catalog),
                      model=MODEL_FAST)
    brief = Brief.model_validate(reply.model_dump())
    limits = tuning.input
    low, high = [None if age is None else min(max(age, 0), limits.brief_age_max)
                 for age in (brief.age_min, brief.age_max)]
    # the ages are the buyer's: a range entirely under buyer_age_min is the product's user (toddlers)
    if high is not None and high < limits.buyer_age_min:
        low = high = None
    elif low is not None and low < limits.buyer_age_min:
        low = limits.buyer_age_min
    price = brief.price_usd
    if price is not None and not (math.isfinite(price) and price >= 0):
        price = None
    return brief.model_copy(update={
        "categories": list(dict.fromkeys(brief.categories)),
        "adjacent_categories": list(dict.fromkeys(brief.adjacent_categories)),
        "conflicts": list(dict.fromkeys(brief.conflicts)),
        "price_usd": price, "age_min": low, "age_max": high,
    })


def decide(has_content: float, business_prob: float, clarity: float, tuning: GateTuning) -> GateResult:
    """The gate: no content -> no_signal; a business or unshoppable buyer -> out_of_scope; an unclear
    product -> clarify; otherwise proceed (weak_fit is decided after matching)."""
    clarity = min(1.0, max(0.0, clarity))
    if has_content < tuning.no_signal_threshold:
        outcome = "no_signal"
    elif business_prob >= tuning.business_threshold:
        outcome = "out_of_scope"
    elif clarity < tuning.proceed_threshold:
        outcome = "clarify"
    else:
        outcome = "proceed"
    return GateResult(outcome=outcome, confidence=clarity, threshold=tuning.proceed_threshold)


def answered_questions(text: str) -> dict[str, str]:
    """Clarify answers already in the text ("- question: answer" lines after ANSWERS_HEADER)."""
    _, header, answers = text.partition(ANSWERS_HEADER)
    if not header:
        return {}
    pairs = (line[2:].split(": ", 1) for line in answers.splitlines() if line.startswith("- "))
    return {pair[0].strip(): pair[1].strip() for pair in pairs if len(pair) == 2}


def _topic(question: str) -> str | None:
    """price, audience or product, by the question's words."""
    words = " " + " ".join(question.lower().replace("?", " ").split()) + " "
    return next((topic for topic, keys in CLARIFY_TOPICS.items() if any(key in words for key in keys)), None)


def clarify_questions(text: str, brief: Brief, llm: LLMProvider, catalog: Catalog,
                      tuning: Tuning) -> list[ClarifyQuestion]:
    """One LLM call writes the questions; code drops any already answered (same words or topic),
    keeps 2–5 options each and at most 3 questions."""
    answered = answered_questions(text)
    categories = sorted({publisher.category for publisher in catalog.publishers})
    system = render(
        "clarify",
        categories=", ".join(CATEGORY_WORDS.get(c, c.replace("_", " ")) for c in categories),
        product=brief.product or FEEDBACK["product_default"],
        facts="; ".join(brief.facts) or FEEDBACK["none"],
        unknowns="\n".join(f"- {unknown}" for unknown in brief.unknowns) or FEEDBACK["clarify_unknowns_default"],
        answered="\n".join(f"- {q}: {a}" for q, a in answered.items()) or FEEDBACK["none"],
    )
    reply = llm.parse(system=system, user=wrap("advertiser_text", text), schema=ClarifyBatch, model=MODEL_FAST)
    asked = {" ".join(q.lower().replace("?", " ").split()) for q in answered}
    asked_topics = {_topic(q) for q in answered} - {None}
    settings = tuning.clarify
    questions = []
    for question in reply.questions:
        repeated = " ".join(question.question.lower().replace("?", " ").split()) in asked
        if repeated or _topic(question.question) in asked_topics:
            continue
        options = question.options[: settings.max_options]
        if len(options) >= settings.min_options:
            questions.append(ClarifyQuestion(question=question.question, options=options))
    return questions[: settings.max_questions]


def apply_note(note: str, brief: Brief, llm: LLMProvider, catalog: Catalog,
               tuning: Tuning) -> tuple[Brief, set[str], set[str], list[str]]:
    """One LLM call reads the note into changes; code keeps only what it can check: publishers and
    personas the note names, catalog category words, ages within the floor and ceiling. Returns the
    changed brief, dropped publisher ids, dropped persona ids and one note per change or refusal."""
    system = render(
        "note_brief",
        publishers=", ".join(publisher.name for publisher in catalog.publishers),
        personas=", ".join(persona.name for persona in catalog.personas),
        categories=", ".join(catalog.vocab),
        brief=brief.model_dump_json(include={"product", "categories", "adjacent_categories", "age_min",
                                             "age_max", "gender_skew", "price_tier"}),
    )
    try:
        changes = llm.parse(system=system, user=wrap("user_note", note), schema=BriefChanges, model=MODEL_FAST)
    except LLMError:
        return brief, set(), set(), [NOTE_NOT_READ]
    text = note.lower()
    notes = list(changes.not_applied)
    dropped_publishers, dropped_personas = set(), set()
    named = {publisher.name.lower(): publisher for publisher in catalog.publishers}
    for name in changes.drop_publishers:
        publisher = named.get(name.lower())
        if publisher and re.search(rf"\b{re.escape(publisher.name.lower())}\b", text):
            dropped_publishers.add(publisher.id)
            notes.append(NOTE_DROPPED.format(name=publisher.name))
        elif publisher:
            notes.append(NOTE_NOT_NAMED.format(name=publisher.name))
    # "pet parent" names The Pet Parent
    named_personas = {re.sub(r"^the\s+", "", persona.name.lower()): persona for persona in catalog.personas}
    for name in changes.drop_personas:
        key = re.sub(r"^the\s+", "", name.lower())
        persona = named_personas.get(key)
        if persona and key in text:
            dropped_personas.add(persona.id)
            notes.append(NOTE_DROPPED.format(name=persona.name))
        elif persona:
            notes.append(NOTE_NOT_NAMED.format(name=persona.name))
    added = [word for word in dict.fromkeys(changes.add_categories)
             if word in catalog.vocab and word not in brief.categories]
    removed = [word for word in dict.fromkeys(changes.remove_categories) if word in brief.categories]
    if added:
        notes.append(NOTE_ADDED.format(words=", ".join(added)))
    if removed:
        notes.append(NOTE_REMOVED.format(words=", ".join(removed)))
    low, high = brief.age_min, brief.age_max
    if changes.age_min is not None or changes.age_max is not None:
        limits = tuning.input
        new_low = changes.age_min if changes.age_min is not None else limits.age_floor
        new_high = changes.age_max if changes.age_max is not None else limits.age_ceiling
        if limits.age_floor <= new_low <= new_high <= limits.age_ceiling:
            low, high = new_low, new_high
            notes.append(NOTE_AGES.format(low=low, high=high))
        else:
            notes.append(NOTE_AGES_REFUSED.format(low=new_low, high=new_high, floor=limits.age_floor,
                                                  ceiling=limits.age_ceiling))
    if not (added or removed or (low, high) != (brief.age_min, brief.age_max)):
        return brief, dropped_publishers, dropped_personas, notes
    categories = [word for word in brief.categories if word not in removed] + added
    changed = brief.model_copy(update={
        "categories": categories,
        "adjacent_categories": [word for word in brief.adjacent_categories
                                if word not in categories and word not in removed],
        "age_min": low, "age_max": high,
    })
    return changed, dropped_publishers, dropped_personas, notes
