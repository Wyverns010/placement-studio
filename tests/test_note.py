"""A note is text the user adds to a step; one LLM call reads it, code checks every change."""
from app.brief import apply_note
from app.llm import FakeProvider
from app.models.brief import BriefChanges
from app.models.scores import PublisherScore
from app.pipeline import stage1
from tests.conftest import CAT, T, brief

DOG = dict(categories=["pet_food"], price_tier="premium", business_model="subscription")
PAWLINE, RUFFCO, TAILCRATE = "pub_007", "pub_009", "pub_018"


def changes(**fields) -> BriefChanges:
    empty = dict(drop_publishers=[], drop_personas=[], add_categories=[], remove_categories=[],
                 age_min=None, age_max=None, not_applied=[])
    return BriefChanges(**{**empty, **fields})


def test_brief_note_drops_only_named_publishers():
    llm = FakeProvider({"BriefChanges": changes(drop_publishers=["Pawline", "Ruffco"])})
    _, dropped, _, notes = apply_note("skip Ruffco", brief(**DOG), llm, CAT, T)
    assert dropped == {RUFFCO}
    assert any("Pawline" in note for note in notes)


def test_brief_note_cannot_drop_every_publisher():
    llm = FakeProvider({"BriefSchema": lambda system, user: None,
                        "BriefChanges": changes(drop_publishers=["Pawline", "Ruffco", "Tailcrate"])})
    result = stage1("We sell dog food", None, "skip Pawline, Ruffco and Tailcrate", brief(**DOG),
                    llm=llm, catalog=CAT, tuning=T)
    assert {p.publisher_id for p in result.publishers if p.recommended} >= {PAWLINE, RUFFCO, TAILCRATE}
    assert any("can't remove every publisher" in note for note in result.agent_notes)


def test_note_naming_nothing_in_the_catalog_changes_nothing():
    llm = FakeProvider({"BriefChanges": changes(drop_publishers=["Amazon"], add_categories=["spaceships"],
                                                not_applied=["There is no Amazon in this catalog."])})
    current, dropped, dropped_personas, notes = apply_note("skip Amazon", brief(**DOG), llm, CAT, T)
    assert current == brief(**DOG) and dropped == set() and dropped_personas == set()
    assert "There is no Amazon in this catalog." in notes


def test_brief_note_applies_ages_and_categories():
    llm = FakeProvider({"BriefChanges": changes(add_categories=["pet_health"], age_min=30, age_max=60)})
    current, _, _, notes = apply_note("add pet health, ages 30 to 60", brief(**DOG), llm, CAT, T)
    assert current.categories == ["pet_food", "pet_health"] and (current.age_min, current.age_max) == (30, 60)
    assert len(notes) == 2


def test_plan_note_refuses_budget_not_in_note():
    from app.models.plan import PlanChanges
    from app.plan import apply_note as apply_plan_note
    pawline = PublisherScore(publisher_id=PAWLINE, name="Pawline", fit=0.7, factors=[], recommended=True,
                             stretch=False, reason="")
    llm = FakeProvider({"PlanChanges": PlanChanges(budget_usd=4000, drop_publishers=[], pacing=None,
                                                   not_applied=[])})
    budget, dropped, pacing, notes = apply_plan_note("keep it cheap", [pawline], llm, T)
    assert budget is None and dropped == set() and pacing is None and notes
