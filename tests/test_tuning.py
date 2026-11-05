from app.models.tuning import Tuning


def test_tuning_loads_defaults():
    t = Tuning()
    assert t.publisher.cutoff == 0.40 and t.gate.proceed_threshold == 0.70
    assert abs(sum(t.publisher.weights.values()) - 1.0) < 1e-9


def test_tuning_new_knobs():
    t = Tuning()
    assert t.ratelimit.global_runs_per_hour == 200
    assert t.input.age_floor == 18 and t.input.age_ceiling == 80


def test_former_constants_are_tunables():
    t = Tuning()
    assert t.llm_timeout_s == 25
    assert (t.clarify.max_questions, t.clarify.max_options, t.clarify.min_options) == (3, 5, 2)


def test_category_words_come_from_prompts():
    from app.prompts import CATEGORY_WORDS
    assert CATEGORY_WORDS.get("home", "home".replace("_", " ")) == "home goods" and CATEGORY_WORDS.get("new_thing", "new_thing".replace("_", " ")) == "new thing"
