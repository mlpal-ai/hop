import time
from collections import deque


class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float, *, clock=None):
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._clock = clock or time.monotonic
        self._tokens = self.capacity
        self._last = self._clock()

    def _refill(self):
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.refill_rate)
        self._last = now

    def allow(self, cost: float = 1.0) -> bool:
        self._refill()
        if cost > self.capacity or cost > self._tokens + 1e-12:
            return False
        self._tokens -= cost
        return True

    def peek(self) -> float:
        self._refill()
        return self._tokens


class SlidingWindow:
    def __init__(self, limit: int, window: float, *, clock=None):
        self.limit = int(limit)
        self.window = float(window)
        self._clock = clock or time.monotonic
        self._events = deque()

    def _prune(self, now):
        cutoff = now - self.window
        while self._events and self._events[0] <= cutoff:
            self._events.popleft()

    def allow(self) -> bool:
        now = self._clock()
        self._prune(now)
        if len(self._events) < self.limit:
            self._events.append(now)
            return True
        return False

    def count(self) -> int:
        self._prune(self._clock())
        return len(self._events)


class KeyedLimiter:
    IDLE = 300.0

    def __init__(self, factory):
        self._factory = factory
        self._limiters = {}  # key -> (limiter, last_used)
        self._clock = None

    def _now(self):
        if self._clock is not None:
            return self._clock()
        return time.monotonic()

    def allow(self, key, *args, **kwargs) -> bool:
        if key not in self._limiters:
            lim = self._factory()
            if self._clock is None:
                c = getattr(lim, "_clock", None)
                if callable(c):
                    self._clock = c
        now = self._now()
        for k in [k for k, (_, last) in self._limiters.items() if now - last > self.IDLE]:
            del self._limiters[k]
        if key not in self._limiters:
            self._limiters[key] = (lim if 'lim' in dir() and key not in self._limiters else self._factory(), now)
            lim2 = self._limiters[key][0]
        limiter, _ = self._limiters[key]
        self._limiters[key] = (limiter, now)
        return limiter.allow(*args, **kwargs)
