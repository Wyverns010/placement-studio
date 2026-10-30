from app.tuning import load_tuning


def test_tuning_loads_defaults():
    t = load_tuning()
    assert t.publisher.cutoff == 0.40 and t.gate.proceed_threshold == 0.70
    assert abs(sum(t.publisher.weights.model_dump().values()) - 1.0) < 1e-9
