from app.ratelimit import RateLimiter


def test_window_expiry_and_pruning():
    now = [0.0]
    rl = RateLimiter(limit=2, window_s=10, clock=lambda: now[0])
    assert rl.check("a") is None and rl.check("a") is None and rl.check("a") == "client"
    now[0] = 10.0
    assert rl.check("a") is None
    assert rl.check("b") is None
    now[0] = 25.0
    assert rl.check("c") is None
    assert set(rl._hits) == {"c"}


def test_global_cap_per_hour():
    now = [0.0]
    rl = RateLimiter(limit=100, window_s=600, global_limit=3, global_window_s=3600,
                     clock=lambda: now[0])
    assert rl.check("a") is None and rl.check("b") is None and rl.check("c") is None
    assert rl.check("d") == "global"
    assert rl.check("e") == "global"
    now[0] = 3599.0
    assert rl.check("f") == "global"
    now[0] = 3600.0
    assert rl.check("f") is None


def test_client_limit_reported_before_global():
    now = [0.0]
    rl = RateLimiter(limit=1, window_s=600, global_limit=5, clock=lambda: now[0])
    assert rl.check("a") is None
    assert rl.check("a") == "client"
    # a refused hit is not recorded globally
    for k in "bcde":
        assert rl.check(k) is None
    assert rl.check("z") == "global"


def test_cost_counts_multiple_runs_and_refuses_if_it_would_overflow():
    now = [0.0]
    rl = RateLimiter(limit=5, window_s=600, global_limit=100, clock=lambda: now[0])
    assert rl.check("a", cost=2) is None and rl.check("a", cost=2) is None
    assert rl.check("a", cost=2) == "client"  # 4 used, 2 more would make 6
    assert rl.check("a") is None and rl.check("a") == "client"
    g = RateLimiter(limit=100, window_s=600, global_limit=3, clock=lambda: now[0])
    assert g.check("x", cost=2) is None and g.check("y", cost=2) == "global"
    assert g.check("y") is None


def test_limits_come_from_tuning():
    from app.models.tuning import Tuning
    r = Tuning().ratelimit
    assert (r.per_client_runs, r.per_client_window_s, r.global_runs_per_hour) == (20, 600, 200)
    assert (r.cost_campaign, r.cost_ads, r.cost_config_note) == (1, 2, 1)
