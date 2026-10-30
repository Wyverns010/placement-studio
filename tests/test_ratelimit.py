from app.ratelimit import RateLimiter


def test_window_expiry_and_pruning():
    now = [0.0]
    rl = RateLimiter(limit=2, window_s=10, clock=lambda: now[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    now[0] = 10.0
    assert rl.allow("a")
    assert rl.allow("b")
    now[0] = 25.0
    assert rl.allow("c")
    assert set(rl._hits) == {"c"}


def test_global_cap_per_hour():
    now = [0.0]
    rl = RateLimiter(limit=100, window_s=600, global_limit=3, global_window_s=3600,
                     clock=lambda: now[0])
    assert rl.check("a") is None and rl.check("b") is None and rl.check("c") is None
    assert rl.check("d") == "global"
    assert not rl.allow("e")
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
