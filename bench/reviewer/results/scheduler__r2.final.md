Verifier is right on #5 and #6 — both were reasoned as if defect #1 were already fixed, and I did not say so. Corrected below. #1–#4 and the nits stand as reported.

## Defects

### 1. CRITICAL — `submit()` calls `notify()` without holding the lock
`src/scheduler.py:32-34`

```python
with self._lock:
    heapq.heappush(self._heap, (priority, next(self._counter), job_id, fn))
self._cv.notify()          # dedented: lock already released
```

`self._cv` wraps `self._lock` (`src/scheduler.py:21-22`). `Condition.notify()` raises `RuntimeError("cannot notify on un-acquired lock")` unless `_is_owned()`. `_lock` is a plain `Lock`, so `Condition._is_owned()` is "try non-blocking acquire; success ⇒ nobody owns it."

Failure scenario: `Scheduler(workers=2); s.submit("a", lambda: 1)`. Both workers are parked in `self._cv.wait(timeout=0.05)` (`src/scheduler.py:46`), which releases the lock, so `_lock` is free → `_is_owned()` is `False` → `submit` raises. The job was already pushed at line 33, so it still runs: the caller gets an exception for a job that succeeded and cannot tell whether submission took effect. This is why `tests/test_sanity.py:5` fails.

Scoping the claim: this is the normal path, not literally every call. `_is_owned()` on a plain `Lock` reports ownership whenever *any* thread holds it, so a `submit` racing another thread's critical section can skip the raise — and then mutates `self._waiters` without owning the lock. Both outcomes are wrong; only the first is deterministic enough to see in a test.

Fix: put the notify inside the critical section (`with self._cv:` around the whole body).

---

### 2. HIGH — An exception from a job permanently kills a worker; jobs then silently never run (violates G1)
`src/scheduler.py:55`

`result = fn()` is unguarded, so a raising job propagates out of `_run` and the thread dies. `self._threads` (`src/scheduler.py:27`) is fixed at construction and never replenished.

Failure scenario: `Scheduler(workers=1)`; submit `"bad"` (raises `ValueError`), then `"good"`. The sole worker dies on `"bad"`; `"good"` stays in `_heap` forever. `shutdown(wait=True)` joins an already-dead thread and returns immediately, reporting clean success while `"good"` never ran and never appears in `results()`. No log, no exception, no metric.

Fix: `try/except BaseException` around `fn()`, record the failure in `_done` as a distinguishable outcome, keep the worker looping.

---

### 3. HIGH — `cancel()` is unsynchronized and races `_run`; returns `True` for a job that runs (violates G3)
`src/scheduler.py:36-40` racing `src/scheduler.py:52-55`

Both sides are check-then-act without the lock: `cancel` reads `_started` (line 37) then writes `_cancelled` (line 39); the worker reads `_cancelled` (line 52) then writes `_started` (line 54), with the lock released since the `heappop` at line 51.

Failure scenario:
1. Worker pops `"j"` (line 51), releases the lock.
2. Worker evaluates `"j" in self._cancelled` (line 52) → `False`.
3. Caller enters `cancel("j")`: `"j" in self._started` (line 37) → `False` → adds to `_cancelled`, **returns `True`**.
4. Worker resumes: `_started.add("j")`, `fn()` runs, result lands in `_done`.

The caller holds an affirmative "cancelled" receipt for work that was performed — for a side-effecting job (charge a card, send mail) that is a user-visible incident.

Fix: take `self._lock` in `cancel()`, and make the worker's cancel-check plus `_started.add` atomic under that same lock — ideally without releasing it after the `heappop`.

---

### 4. MEDIUM — `shutdown(wait=True)` can return while jobs are still executing (violates G4)
`src/scheduler.py:66-68`

`t.join(timeout=5)` discards its outcome; `join` returns `None` on timeout and `t.is_alive()` is never checked, so a timed-out join is indistinguishable from a completed one.

Failure scenario: submit one job that sleeps 6s, call `shutdown(wait=True)`. After 5s the join gives up and `shutdown` returns normally while the job is still running, contradicting G4. A caller that then closes a DB handle or exits the process truncates that job — and since the threads are `daemon=True` (`src/scheduler.py:27`), interpreter exit kills them mid-job.

Fix: join without a timeout, or keep the bound and surface a status/raise when `t.is_alive()` after the join.

---

### 5. MEDIUM — No lifecycle guard on `submit()`; post-shutdown jobs are enqueued and never run (violates G1)
`src/scheduler.py:31-34`, with `src/scheduler.py:47-48`

*Corrected from my previous report.* `submit` never checks `self._stop`. Once workers observe `_stop` with an empty heap and return at lines 47-48, nothing consumes `_heap`.

What actually happens today: `s.shutdown(wait=True)`, then `s.submit("late", fn)` pushes the entry at line 33 and then **raises `RuntimeError` at line 34** — the defect-#1 notify bug, not a shutdown check. My earlier claim of "no error / silently accepts" was wrong and the verifier's direct execution refutes it.

The defect is still real, on two counts:
- The `RuntimeError` is the same generic "cannot notify on un-acquired lock" every other `submit` raises. It does not tell the caller the scheduler is shut down, so it cannot be handled distinctly.
- `"late"` is nonetheless sitting in `_heap` and will never run or appear in `results()` — accepted work, permanently lost.

Note the ordering dependency: fixing defect #1 *removes* the incidental exception and turns this into fully silent loss. Fix #1 and #5 together.

Fix: under the lock, `if self._stop: raise RuntimeError("scheduler is shut down")` before the push.

---

## Hazards (correct today, no demonstrated failure)

### 6. HAZARD — the lock around `results()` is decorative
`src/scheduler.py:59-60` vs. writers at `src/scheduler.py:39`, `54`, `56`

*Downgraded and re-scoped.* `results()` acquires `self._lock`; every writer to `_done`, `_started`, and `_cancelled` writes without it. So the lock grants no mutual exclusion — it only makes the code read as synchronized.

I withdraw my previous "torn or resized list" claim: it was asserted without a reproducer and is not observable on this interpreter (`sys._is_gil_enabled()` is `True`, and `list.append` and the list copy are each atomic under the GIL). There is no correctness failure here today.

What remains reportable is maintenance risk, not behavior: `_done`'s safety rests on a CPython implementation detail rather than on the code's own synchronization, and the misleading `with self._lock` invites the next maintainer to add a genuinely non-atomic read-modify-write under it. The demonstrated cost of this same unlocked-state pattern is defect #3, which is where the real bug already is.

Fix: perform the writes under `self._lock`, or drop the lock in `results()` and document the GIL reliance. The first is correct.

---

## Nits
- `src/scheduler.py:49-50` — unreachable. Exiting the `while` at line 45 implies a non-empty heap or `_stop`, and the `_stop`-with-empty-heap case already returned at lines 47-48.
- `src/scheduler.py:46` — each idle worker wakes ~20×/s until shutdown. This polling is what currently masks defect #1; only remove the timeout once notify is correct.
- `src/scheduler.py:39`, `52-53` — `_cancelled` grows without bound; IDs are never discarded after a job is skipped or completed.
- `src/scheduler.py:36-40` — `cancel("never-submitted")` returns `True`, indistinguishable from cancelling a real pending job.

## On "fix any defect"

Unchanged and worth restating plainly: I cannot apply these. This session is read-only — there is no Write/Edit tool and `Bash` returns `Permission denied: recon mode is read-only: changes are blocked`, so I could neither patch `src/scheduler.py` nor run `python -m pytest` against a patch. Every fix above is a described proposal, unapplied and unverified by me. To land them, re-run in a write-capable profile; `python -m pytest` should fail at `tests/test_sanity.py:5` on defect #1 before any edit, and that is the regression baseline.

**Verdict: not shippable.** The normal `submit()` path raises (#1), and three of the four documented guarantees are violable — G1 via #2 and #5, G3 via #3, G4 via #4 — with #2 and #5 failing silently.