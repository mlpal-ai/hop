from src.ratekit import TokenBucket, SlidingWindow, KeyedLimiter


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def tick(self, dt): self.t += dt


def test_bucket_starts_full_and_refills():
    c = Clock()
    b = TokenBucket(10, 2.0, clock=c)
    assert b.allow(10) is True
    assert b.allow(0.5) is False
    c.tick(1.0)
    assert abs(b.peek() - 2.0) < 1e-9
    assert b.allow(2.0) is True
    c.tick(100.0)
    assert abs(b.peek() - 10.0) < 1e-9, "must cap at capacity"


def test_bucket_fractional_and_no_partial_consume():
    c = Clock()
    b = TokenBucket(1.0, 1.0, clock=c)
    assert b.allow(0.6) and b.allow(0.4)
    assert b.allow(0.1) is False
    c.tick(0.05)
    assert b.allow(0.1) is False  # only 0.05 refilled
    assert abs(b.peek() - 0.05) < 1e-9, "failed allow must not consume"


def test_bucket_cost_over_capacity():
    b = TokenBucket(5, 1000.0, clock=Clock())
    assert b.allow(5.001) is False


def test_window_half_open_boundary():
    c = Clock()
    w = SlidingWindow(2, 10.0, clock=c)
    assert w.allow() and w.allow() and not w.allow()
    c.tick(10.0)  # first two events now exactly at now - window -> excluded (half-open)
    assert w.count() == 0
    assert w.allow() is True


def test_window_denied_not_recorded():
    c = Clock()
    w = SlidingWindow(1, 5.0, clock=c)
    assert w.allow()
    for _ in range(50):
        assert not w.allow()
    c.tick(5.01)
    assert w.allow() is True, "denied attempts must not extend occupancy"


def test_keyed_isolation_and_eviction():
    c = Clock()
    kl = KeyedLimiter(lambda: TokenBucket(1, 0.0, clock=c))
    assert kl.allow("a") and kl.allow("b")
    assert not kl.allow("a"), "keys must be isolated"
    c.tick(301)
    assert kl.allow("z")          # triggers lazy eviction of idle keys
    assert kl.allow("a") is True, "evicted key must restart fresh"
