import math

import pytest
from pydantic import ValidationError

from app.brief import brief_schema, clarify_questions, decide, understand
from app.constants.brief import NO_SIGNAL_QUESTIONS
from app.llm import FakeProvider
from app.loaders import load_catalog
from app.models.brief import Brief, ClarifyBatch, ClarifyQuestion
from app.pipeline import stage1
from tests.conftest import CAT, T, brief

GATE = T.gate

# ---- understand ----


def _payload(**over):
    base = dict(
        describes_business=True, product="dog food", audience_type="consumer",
        categories=["pet_food"], adjacent_categories=[], conflicts=[],
        price_usd=None, price_tier="mid", business_model="one_off",
        age_min=None, age_max=None, gender_skew="unknown",
        facts=[], unknowns=[], self_confidence=0.8,
    )
    base.update(over)
    return base


def test_understand_returns_brief_with_vocab_terms():
    cat = load_catalog()
    fake = FakeProvider({"BriefSchema": brief_schema(cat)(**_payload())})
    brief = understand("premium dog food", cat, fake, T)
    assert isinstance(brief, Brief)
    assert brief.categories == ["pet_food"]
    assert fake.calls[0]["schema"] == "BriefSchema"


def test_understand_schema_rejects_out_of_vocab():
    cat = load_catalog()
    with pytest.raises(ValidationError):
        brief_schema(cat)(**_payload(categories=["outdoor"]))
    with pytest.raises(ValidationError):
        brief_schema(cat)(**_payload(conflicts=["not_a_conflict"]))


def test_understand_prompt_contains_vocab_and_text():
    cat = load_catalog()
    fake = FakeProvider({"BriefSchema": brief_schema(cat)(**_payload())})
    understand("we sell kibble", cat, fake, T)
    call = fake.calls[0]
    assert "pet_food" in call["system"]
    assert cat.conflict_vocab[0] in call["system"]
    assert call["user"] == "<advertiser_text>we sell kibble</advertiser_text>"


def test_understand_cleans_up_the_reply():
    cat = load_catalog()
    reply = brief_schema(cat)(**_payload(categories=["pet_food"] * 3, adjacent_categories=["pet", "pet", "home"],
                                         price_usd=math.inf, age_min=-3, age_max=400))
    b = understand("dog food", cat, FakeProvider({"BriefSchema": reply}), T)
    assert b.categories == ["pet_food"] and b.adjacent_categories == ["pet", "home"]
    assert b.price_usd is None and b.age_min == T.input.buyer_age_min and b.age_max == T.input.brief_age_max


def test_vocab_groups_by_publisher_category_plus_interest_terms():
    cat = load_catalog()
    groups = cat.vocab_groups
    assert {"treats", "toys", "pet_food"} <= set(groups["pet"])
    assert "supplements" in groups["wellness_dtc"] and "basics" in groups["apparel"]
    interests = cat.interest_terms
    assert "pet_health" in interests and "treats" not in interests
    # the groups and interest terms cover exactly the schema vocabulary
    assert set(groups) | {t for ts in groups.values() for t in ts} | set(interests) == set(cat.vocab)


def test_understand_prompt_renders_grouped_vocab_and_parent_rule():
    cat = load_catalog()
    pet_line = "- pet: " + ", ".join(cat.vocab_groups["pet"])
    assert "treats" in pet_line and "toys" in pet_line
    fake = FakeProvider({"BriefSchema": brief_schema(cat)(**_payload())})
    understand("protein bars", cat, fake, T)
    system = fake.calls[0]["system"]
    assert pet_line in system and "pet_health" in system
    assert "only for products for animals" in system
    assert "include that publisher category (the term left of the colon)" in system
    assert "{" not in system


def test_schema_vocab_unchanged_by_grouping():
    cat = load_catalog()
    groups = cat.vocab_groups
    shown = set(groups) | {t for ts in groups.values() for t in ts} | set(cat.interest_terms)
    assert shown == set(cat.vocab)  # the grouped prompt text names exactly the schema's terms
    for term in cat.vocab:
        b = brief_schema(cat)(**_payload(categories=[term]))
        assert b.categories == [term]


@pytest.mark.parametrize("lo,hi,want", [(1, 3, (None, None)), (13, 25, (18, 25)), (35, None, (35, None)),
                                         (None, 12, (None, None)), (25, 40, (25, 40))])
def test_understand_keeps_buyer_ages_only(lo, hi, want):
    cat = load_catalog()
    reply = brief_schema(cat)(**_payload(age_min=lo, age_max=hi))
    b = understand("x", cat, FakeProvider({"BriefSchema": reply}), T)
    assert (b.age_min, b.age_max) == want


# ---- gate ----


@pytest.mark.parametrize(
    "has_content,business_prob,clarity,expected",
    [
        (0.29, 0.0, 0.9, "no_signal"),
        (0.30, 0.0, 0.9, "proceed"),
        (0.30, 0.50, 0.9, "out_of_scope"),
        (1.0, 0.49, 0.9, "proceed"),
        (1.0, 0.0, 0.69, "clarify"),
        (1.0, 0.0, 0.70, "proceed"),
    ],
)
def test_decide_branches(has_content, business_prob, clarity, expected):
    r = decide(has_content, business_prob, clarity, GATE)
    assert r.outcome == expected
    assert r.confidence == clarity
    assert r.threshold == GATE.proceed_threshold


def test_decide_clamps_clarity():
    r = decide(1.0, 0.0, 1.2, GATE)
    assert r.confidence == 1.0 and r.outcome == "proceed"


@pytest.mark.parametrize("brief_kw,expected", [
    (dict(audience_type="business"), "out_of_scope"),
    # local in-person services, job ads, charities, political messages: nothing a shopper buys online
    (dict(audience_type="not_shoppable"), "out_of_scope"),
    (dict(describes_business=False), "no_signal"),
    (dict(self_confidence=0.4), "clarify"),
    (dict(), "proceed"),
    (dict(audience_type="unclear", self_confidence=0.4), "clarify"),
    (dict(audience_type="unclear", self_confidence=0.85), "proceed"),
])
def test_stage1_gate_reads_the_brief(brief_kw, expected):
    llm = FakeProvider({"ClarifyBatch": ClarifyBatch(questions=[])})
    r = stage1("x", None, None, brief(**brief_kw), llm=llm, catalog=CAT, tuning=T)
    assert r.gate.outcome == expected


# ---- clarify ----

def test_clarify_trims_options_and_drops_short_questions():
    out = ClarifyBatch(questions=[
        ClarifyQuestion(question="a?", options=list("123456")),
        ClarifyQuestion(question="b?", options=["only"]),
        ClarifyQuestion(question="c?", options=["x", "y"]),
        ClarifyQuestion(question="d?", options=["x", "y"]),
        ClarifyQuestion(question="e?", options=["x", "y"]),
    ])
    llm = FakeProvider({"ClarifyBatch": out})
    qs = clarify_questions("vague", brief(unknowns=["price"]), llm, CAT, T)
    assert [q.question for q in qs] == ["a?", "c?", "d?"]
    assert len(qs[0].options) == 5
    assert "price" in llm.calls[0]["user"] + llm.calls[0]["system"]


def test_clarify_prompt_renders_catalog_categories():
    llm = FakeProvider({"ClarifyBatch": ClarifyBatch(questions=[])})
    clarify_questions("vague", brief(), llm, CAT, T)
    system = llm.calls[0]["system"]
    assert "{categories}" not in system
    for word in ("pet", "apparel", "home goods", "meal kits", "drinks", "fitness/wellness services"):
        assert word in system


def test_no_signal_questions_static():
    assert len(NO_SIGNAL_QUESTIONS) == 3
    assert all(2 <= len(q.options) <= 5 for q in NO_SIGNAL_QUESTIONS)
    assert NO_SIGNAL_QUESTIONS[0].question == "What do you sell?"


def test_clarify_never_reasks_an_answered_question():
    out = ClarifyBatch(questions=[
        ClarifyQuestion(question="What kind of product is it?", options=["Beauty", "Apparel"]),
        ClarifyQuestion(question="Roughly what does it cost?", options=["Under $30", "$30+"]),
        ClarifyQuestion(question="Who is it mainly for?", options=["Adults", "Kids"]),
        ClarifyQuestion(question="Is it a product or service?", options=["Product", "Service"]),
    ])
    llm = FakeProvider({"ClarifyBatch": out})
    text = ("We help people feel better.\n\nAdditional details:\n"
            "- What kind of product is it?: Beauty\n- Who is it for?: Adults")
    qs = clarify_questions(text, brief(), llm, CAT, T)
    assert [q.question for q in qs] == ["Roughly what does it cost?"]
    system = llm.calls[0]["system"]
    assert "- What kind of product is it?: Beauty" in system and "- Who is it for?: Adults" in system
