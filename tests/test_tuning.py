import pytest

from app.loaders import load_tuning


def test_tuning_loads_defaults():
    t = load_tuning()
    assert t.publisher.cutoff == 0.40 and t.gate.proceed_threshold == 0.70
    assert abs(sum(t.publisher.weights.values()) - 1.0) < 1e-9


def test_tuning_new_knobs():
    t = load_tuning()
    assert t.ratelimit.global_runs_per_hour == 200
    assert t.input.age_floor == 18 and t.input.age_ceiling == 80


def test_former_constants_are_tunables():
    t = load_tuning()
    assert t.llm_timeout_s == 25
    assert (t.clarify.max_questions, t.clarify.max_options, t.clarify.min_options) == (3, 5, 2)


def test_load_tuning_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_tuning().budget.round_to_usd == 500


def test_category_words_come_from_prompts():
    from app.prompts import CATEGORY_WORDS
    assert CATEGORY_WORDS.get("home", "home".replace("_", " ")) == "home goods" and CATEGORY_WORDS.get("new_thing", "new_thing".replace("_", " ")) == "new thing"


def test_a_key_the_code_does_not_read_is_refused(tmp_path):
    from pydantic import ValidationError

    from app.constants.paths import TUNING_PATH
    extra = tmp_path / "tuning.yaml"
    extra.write_text(TUNING_PATH.read_text().replace("clarify:\n", "clarify:\n  max_turns: 3\n", 1))
    with pytest.raises(ValidationError, match="max_turns"):
        load_tuning(extra)
