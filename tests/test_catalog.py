from app.loaders import load_catalog


def test_catalog_counts_and_derived_fields():
    c = load_catalog()
    assert len(c.publishers) == 20 and len(c.personas) == 10
    p = c.publisher_by_id["pub_007"]  # Pawline
    assert (p.age_min, p.age_max, p.income_rank) == (30, 55, 2)
    assert {"pet", "pet_food", "subscription"} <= p.tags
    assert "pet_health" in c.vocab and "pet_food" in c.vocab
    assert "luxury positioning" in c.conflict_vocab
