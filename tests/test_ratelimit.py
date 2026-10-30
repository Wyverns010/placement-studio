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
