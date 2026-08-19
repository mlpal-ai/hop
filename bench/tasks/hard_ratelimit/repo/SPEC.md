# ratekit SPEC

Implement `src/ratekit.py` exposing exactly:

## class TokenBucket(capacity: float, refill_rate: float, *, clock=None)
Token-bucket limiter. Starts FULL. `refill_rate` = tokens/second, continuous refill,
never exceeding `capacity`. `clock` is an injectable zero-arg callable returning
seconds (float); default = time.monotonic.
- allow(cost: float = 1.0) -> bool — consume `cost` tokens if available (after
  refilling by elapsed time), else consume nothing and return False. cost may be
  fractional. cost > capacity must always return False (never blocks forever).
- peek() -> float — current token count (post-refill), no consumption.

## class SlidingWindow(limit: int, window: float, *, clock=None)
Exact sliding-window counter (not fixed buckets): allow() returns True and records
the event iff strictly fewer than `limit` events occurred in the half-open interval
(now - window, now]. Denied calls are NOT recorded. Memory must stay O(limit):
prune expired timestamps on every call.
- allow() -> bool
- count() -> int — events currently inside the window (post-prune).

## class KeyedLimiter(factory)
Wraps per-key limiters. `factory` is a zero-arg callable returning a fresh limiter.
- allow(key, *args, **kwargs) -> bool — delegates to that key's limiter, creating
  it on first use.
- Eviction: a key whose limiter has been idle (no allow() calls) for over 300
  seconds is dropped on the NEXT allow() call for ANY key (checked lazily; use the
  same clock as created limiters if the factory product exposes one, else
  time.monotonic).

Determinism: all time-dependent behavior must flow through the injected clock so
tests can drive time manually. No threads, no sleeps.
