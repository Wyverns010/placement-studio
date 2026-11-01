from app.tuning import load_tuning


def test_tuning_loads_defaults():
    t = load_tuning()
    assert t.publisher.cutoff == 0.40 and t.gate.proceed_threshold == 0.70
    assert abs(sum(t.publisher.weights.model_dump().values()) - 1.0) < 1e-9


def test_tuning_new_knobs():
    t = load_tuning()
    assert t.ratelimit.global_runs_per_hour == 200
    assert t.audience.age_floor == 18 and t.audience.age_ceiling == 80


def test_former_constants_are_tunables():
    t = load_tuning()
    assert t.llm.timeout_s == 25
    assert (t.clarify.max_questions, t.clarify.max_options, t.clarify.min_options) == (3, 5, 2)
    assert (t.stage1.top_publishers_shown, t.stage1.clarify_publishers_shown) == (5, 3)


def test_load_tuning_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_tuning().budget.round_to_usd == 500


def test_category_words_come_from_prompts():
    from app.catalog import load_catalog
    from app.create import category_words
    from app.prompts import category_word
    assert category_word("home") == "home goods" and category_word("new_thing") == "new thing"
    words = category_words(load_catalog())
    assert "home goods" in words and "drinks" in words


def test_pipeline_slices_follow_tuning():
    from app.pipeline import _pub_data
    from app.models import PublisherScore
    t = load_tuning().model_copy(deep=True)
    pubs = [PublisherScore(publisher_id=f"p{i}", name=f"P{i}", fit=1 - i / 10, factors=[],
                           recommended=True, stretch=False, reason="") for i in range(8)]
    t.stage1.top_publishers_shown, t.stage1.clarify_publishers_shown = 2, 1
    assert len(_pub_data(pubs, t)["top"]) == 2
    assert _pub_data(pubs, t, "clarify")["recommended"] == ["p0"]
