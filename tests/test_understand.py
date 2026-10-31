import pytest
from pydantic import ValidationError

from app.catalog import load_catalog
from app.llm import FakeProvider
from app.models import Brief
from app.understand import brief_schema, understand


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
    brief = understand("premium dog food", cat, fake)
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
    understand("we sell kibble", cat, fake)
    call = fake.calls[0]
    assert "pet_food" in call["system"]
    assert cat.conflict_vocab[0] in call["system"]
    assert call["user"] == "<advertiser_text>we sell kibble</advertiser_text>"


def test_clamp_brief_to_input_caps():
    import math
    from app.understand import clamp_brief
    from tests.conftest import T, brief
    i = T.input
    b = brief(product="p" * 300, facts=["f" * 500] * 15, unknowns=["u" * 500] * 12,
              categories=["pet_food"] * 30, adjacent_categories=["pet", "pet", "home"] * 10,
              conflicts=[], price_usd=math.inf, age_min=-3, age_max=400)
    c = clamp_brief(b, T)
    assert len(c.product) == i.brief_product_max_chars
    assert len(c.facts) == i.brief_list_max_items and all(len(f) == i.brief_item_max_chars for f in c.facts)
    assert len(c.unknowns) == i.brief_list_max_items
    assert c.categories == ["pet_food"] and c.adjacent_categories == ["pet", "home"]
    assert c.price_usd is None and c.age_min == 0 and c.age_max == i.brief_age_max
    ok = brief(product="dog food", facts=["a"], price_usd=60, age_min=30, age_max=50)
    assert clamp_brief(ok, T) == ok
