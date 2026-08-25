All external verification (Bash, WebFetch, stdlib reads) is blocked in this profile, so the analysis below is static — I flag the one place where that matters.

## Findings

### D1 — CRITICAL: `submit()` raises `RuntimeError` on essentially every call — the scheduler doesn't work at all

`src/scheduler.py:32-34`

```python
with self._lock:
    heapq.heappush(...)
self._cv.notify()          # line 34 — lock already released
```

`self._cv` is a `Condition` wrapping `self._lock` (`src/scheduler.py:21-22`). `Condition.notify()` is documented to raise `RuntimeError` if the calling thread does not hold the lock, and CPython implements that check as `if not self._is_owned(): raise RuntimeError("cannot notify on un-acquired lock")`. The `with self._lock:` block on line 32 exits before line 34, so the lock is not held.

Nastier detail: because `_lock` is a plain `Lock` (not `RLock`), `Condition._is_owned()` degrades to "is the lock currently held by *anybody*" (it probes `acquire(False)`). So the outcome is **timing-dependent**:
- Lock free at line 34 (the overwhelmingly common case — workers spend their time inside `cv.wait()`, which releases the lock) → `RuntimeError` propagates to the caller.
- A worker happens to hold the lock at that instant → no exception, but `notify()` then mutates the condition's `_waiters` deque with no lock held, which is an unsynchronized-mutation race.

**Failure scenario:** the shipped test at `tests/test_sanity.py:5` — `s.submit("a", lambda: 1)` — raises `RuntimeError: cannot notify on un-acquired lock` before the assert is ever reached. Every guarantee G1–G4 is vacuous because no job can be enqueued.

**Fix:** move `notify()` inside the critical section (`with self._cv:` around push + notify).

---

### D2 — HIGH: an exception in a job silently kills a worker thread forever (G1 + G4)

`src/scheduler.py:55` — `result = fn()` is unguarded, inside the `while True:` loop of `_run`.

Any exception raised by user code propagates out of `_run`, terminating that worker thread permanently. There is no supervision, no restart, no record. Worse, `shutdown(wait=True)` joins a dead thread instantly and returns normally (`src/scheduler.py:66-68`), so the failure is indistinguishable from success.

**Failure scenario:** `Scheduler(workers=2)`; submit `lambda: 1/0` twice. Both workers die. Now submit `("c", lambda: 3)` — it sits in `_heap` forever. `shutdown(wait=True)` returns immediately and cleanly. `results()` returns `[]`. Job "c" never ran and nothing reported an error → G1 ("every submitted job runs exactly once") and G4 ("shutdown runs all pending jobs to completion") both violated *silently*.

---

### D3 — HIGH: `cancel()` returns `True` for a job that then runs anyway (G3)

`src/scheduler.py:36-40` vs `src/scheduler.py:51-55`.

The worker pops the job (line 51), checks `_cancelled` (line 52), and only then records `_started` (line 54) — with the lock released after line 51. `cancel()` reads `_started` (line 37) and writes `_cancelled` (line 39) with no lock at all. The two sequences interleave.

**Failure scenario:**
1. Worker pops `("x", fn)` at line 51 and releases the lock.
2. Worker evaluates line 52: `"x" not in self._cancelled` → falls through. Thread is preempted before line 54.
3. Caller runs `cancel("x")`: line 37 sees `"x" not in self._started` → line 39 adds to `_cancelled` → **returns `True`**.
4. Worker resumes: line 54 adds `"x"` to `_started`, line 55 executes `fn()`.

`cancel` promised the job would not run; it ran. G3 violated. The check-and-claim (`_cancelled` test + `_started` add) must be atomic with the pop, under the same lock.

---

### D4 — HIGH: `shutdown(wait=True)` can return while jobs are still executing (G4)

`src/scheduler.py:68` — `t.join(timeout=5)`.

The 5-second timeout is hard-coded, the return value of `join` is discarded, and `t.is_alive()` is never checked. G4 states "no job may run after `shutdown()` returns."

**Failure scenario:** submit a job that takes 10s (`lambda: time.sleep(10)`). `shutdown(wait=True)` returns after ~5s while the worker is still inside `fn()`. Caller then reads `results()` and gets an incomplete list, or the process exits — and since the threads are `daemon=True` (`src/scheduler.py:27`), interpreter shutdown kills the job mid-flight. Also note the timeout is *per thread*, so with 4 workers the call can block up to 20s, which is not the documented contract either.

**Fix:** expose a caller-supplied `timeout` (default `None` = block), and after joining, if any thread `is_alive()`, raise rather than return a false success.

---

### D5 — MEDIUM: `cancel()` performs completely unsynchronized shared-state access

`src/scheduler.py:36-40` never acquires `self._lock`, while `_run` mutates `_started` at line 54 and reads `_cancelled` at line 52 from N worker threads. Under CPython the GIL makes individual `set` ops non-corrupting, so this is not a crash today — but the method has no memory-ordering or atomicity story, it is the direct cause of D3, and it breaks outright under free-threaded builds (PEP 703, `python3.13t`+). This is the root cause to fix, not just a style issue.

---

### D6 — MEDIUM: `submit()` after `shutdown()` is silently accepted and never runs (G1)

`src/scheduler.py:31-34` has no `_stop` guard, and workers exit at `src/scheduler.py:47-48` once `_stop` is set and the heap drains.

**Failure scenario:** `s.shutdown(); s.submit("z", fn)` → the tuple is pushed onto `_heap`, all workers have already returned, no exception is raised, `results()` never contains `"z"`. There is also a live race even without an explicit ordering violation: a `submit` concurrent with the last worker's line-47 check lands in the heap just after that worker decides to return. Submitting to a closed scheduler must raise.

---

### D7 — MEDIUM: `cancel()` on an unknown id permanently blacklists that id (G1)

`src/scheduler.py:37-39`: for a `job_id` that was never submitted, line 37 is false, so line 39 adds it to `_cancelled` and returns `True`. Nothing ever removes entries from `_cancelled`.

**Failure scenario:** `s.cancel("reprot-nightly")` (typo, or a speculative cancel of a job that hasn't been enqueued yet) returns `True`. Later `s.submit("reprot-nightly", fn)` → the worker pops it, line 52 matches, `continue` — the job is dropped with no error and no record. G1 violated.

---

### D8 — LOW (hazard): `results()`'s lock is decorative

`src/scheduler.py:59-60` acquires `self._lock` to copy `_done`, but the only writer (`src/scheduler.py:56`) appends *without* the lock; same for `_started` at line 54. A lock that no writer respects provides no mutual exclusion — it only creates the appearance of safety for the next maintainer. Correct today solely because `list.append` is atomic under the GIL; it breaks on free-threaded interpreters and it is exactly the kind of asymmetry that D3 grew out of.

---

### D9 — LOW (hazard): idle workers busy-poll

`src/scheduler.py:45-46`: `self._cv.wait(timeout=0.05)` inside the empty-heap loop means every worker wakes 20×/second forever, even with zero jobs (`Scheduler(workers=32)` → 640 wakeups/s at idle). The timeout appears to exist to paper over missed notifications; once D1 is fixed, an untimed `wait()` is correct and free.

### D10 — NIT: unbounded growth

`_cancelled` (`src/scheduler.py:39`) and `_started` (`src/scheduler.py:54`) are never pruned. For a long-lived scheduler processing millions of jobs this is an unbounded memory leak.

---

## On "fix any defect you find"

I can't apply it. This session is the read-only reviewer profile: there is no Write/Edit tool, and `Bash`/`WebFetch` are hard-denied (`Permission denied: recon mode is read-only: changes are blocked`), so I also could not run the test suite to confirm D1's failure empirically. **The patch below is unapplied and untested** — please re-run in a write-capable profile if you want it landed and verified.

Precise fix for `src/scheduler.py`:

```python
class SchedulerClosed(RuntimeError):
    """Raised when submitting to a scheduler that is shutting down."""


    def submit(self, job_id, fn, priority=10):
        with self._cv:                                   # D1: notify under the lock
            if self._stop:                               # D6
                raise SchedulerClosed(f"scheduler is shut down; rejected {job_id!r}")
            if job_id in self._cancelled:                # D7: don't resurrect a stale cancel
                raise ValueError(f"{job_id!r} was cancelled before submission")
            heapq.heappush(self._heap, (priority, next(self._counter), job_id, fn))
            self._cv.notify()

    def cancel(self, job_id) -> bool:
        with self._cv:                                   # D5
            if job_id in self._started:
                return False
            self._cancelled.add(job_id)
            return True

    def _run(self):
        while True:
            with self._cv:
                while not self._heap and not self._stop:
                    self._cv.wait()                      # D9: no timeout needed now
                if not self._heap:                       # _stop and drained
                    return
                _, _, job_id, fn = heapq.heappop(self._heap)
                if job_id in self._cancelled:
                    continue
                self._started.add(job_id)                # D3: claim atomically with the pop
            try:
                result = fn()
            except Exception as exc:                     # D2: a bad job must not kill the worker
                with self._cv:
                    self._errors.append((job_id, exc))
                continue
            with self._cv:                               # D8
                self._done.append((job_id, result))

    def shutdown(self, wait: bool = True, timeout: float | None = None):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if wait:
            deadline = None if timeout is None else time.monotonic() + timeout
            for t in self._threads:
                t.join(None if deadline is None else max(0.0, deadline - time.monotonic()))
            if any(t.is_alive() for t in self._threads):  # D4: never a silent partial shutdown
                raise TimeoutError("workers still running at shutdown timeout")
```

Plus `self._errors = []` in `__init__` and an `errors()` accessor mirroring `results()`, so D2's failure mode is observable rather than silent.

Two things the fix deliberately does **not** do, worth your call: it rejects `submit()` after `shutdown()` rather than queueing (D6), and it rejects re-submitting a previously-cancelled `job_id` rather than clearing the tombstone (D7) — both are behavior changes to an under-specified corner of the contract, and both should be written into the G1/G3 wording in the module docstring. Neither `_cancelled` nor `_started` is pruned (D10); bounding those needs a retention policy you should choose.

The test suite is also structurally inadequate: `tests/test_sanity.py` is a single happy-path test, and `README.md:3` openly concedes the concurrency guarantees are untested. D2, D3, D4 and D6 are each directly testable deterministically (raising job; a `threading.Event` seam between pop and run to force the D3 interleave; a sleeping job vs. a short shutdown timeout; submit-after-shutdown) and should not merge without regression tests.

**Verdict:** Not shippable — `submit()` is broken outright (D1), and once that's fixed three of the four documented guarantees (G1, G3, G4) still fail under concurrency, all of them silently.