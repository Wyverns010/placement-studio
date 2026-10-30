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
