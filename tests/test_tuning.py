from app.tuning import load_tuning


def test_tuning_loads_defaults():
    t = load_tuning()
    assert t.publisher.cutoff == 0.40 and t.gate.proceed_threshold == 0.70
    assert abs(sum(t.publisher.weights.model_dump().values()) - 1.0) < 1e-9


def test_tuning_new_knobs():
    t = load_tuning()
    assert t.ratelimit.global_runs_per_hour == 200
    assert t.audience.age_floor == 18 and t.audience.age_ceiling == 80
