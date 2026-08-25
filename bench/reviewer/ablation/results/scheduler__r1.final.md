Bash and Monitor are both denied in this profile, and there is no Write/Edit tool — so I could not run the test suite and I cannot apply fixes. Everything below is derived from reading the source plus CPython's `threading` semantics; I've flagged where a defect is timing-dependent. See the note at the end about the fix request.

## Defects

### 1. `submit()` calls `notify()` without holding the lock — raises `RuntimeError` to the caller after the job was already enqueued (Critical)

`src/scheduler.py:32-34`: the `heappush` is inside `with self._lock:`, but `self._cv.notify()` on line 34 is dedented back out of the block, so the lock is released before notifying.

`threading.Condition.notify()` starts with `if not self._is_owned(): raise RuntimeError("cannot notify on un-acquired lock")`. Because `_cv` was built over a plain `threading.Lock` (`src/scheduler.py:21-22`), `Condition` cannot borrow a real `_is_owned` and falls back to the probe implementation (`acquire(False)` → success means "not owned"). With the lock free, the probe succeeds and `notify()` raises.

Failure scenario — this is the sanity test: `tests/test_sanity.py:5` calls `s.submit("a", lambda: 1)`. Both workers are parked in `self._cv.wait(timeout=0.05)` (`src/scheduler.py:46`), which releases the lock, so the lock is free when line 34 runs → `RuntimeError: cannot notify on un-acquired lock` propagates out of `submit()`. But the job is *already on the heap* (line 33). The caller sees a failed submit, retries with the same `job_id`, and the job now runs twice — a direct G1 ("exactly once") violation, with two entries in `results()`.

Two aggravating notes: (a) the error is non-deterministic — if a worker happens to be inside its lock-held window on lines 45-51 at that instant, the probe fails, `_is_owned()` returns `True` spuriously, and `notify()` proceeds to mutate `_waiters` with no mutual exclusion; (b) the 50 ms polling on line 46 means jobs still get picked up despite the lost/failed notify, which is exactly why this bug can survive in a codebase.

Fix: use one block — `with self._cv: heapq.heappush(...); self._cv.notify()`.

### 2. An exception from a job kills the worker thread permanently (High)

`src/scheduler.py:55`: `result = fn()` is unguarded, inside the `while True` loop of `_run`. Any exception escapes `_run` and terminates that thread.

Failure scenario: `Scheduler(workers=1)`; `submit("a", lambda: 1/0)`, then `submit("b", good_fn)`. Job "a" raises, the single worker dies. "b" stays on the heap forever and never runs (G1 violated). Then `shutdown(wait=True)` (`src/scheduler.py:66-68`) joins a thread that is already dead, so it returns immediately and reports success — G4 ("runs all pending jobs to completion") silently violated, and `results()` is missing "b" with no error anywhere. With N workers this degrades one worker per poison job until throughput reaches zero. Fix: wrap `fn()` in `try/except BaseException`, record the failure in `_done` (or a `_failed` list) so the outcome is observable, and continue the loop.

### 3. `cancel()` is entirely unsynchronized — returns `True` for a job that then runs (High, G3)

`src/scheduler.py:36-40` touches `_started` and `_cancelled` with no lock held, and the worker's check/mark pair is split across an unlocked region: the `_cancelled` test is at `src/scheduler.py:52` and the `_started` insert at `src/scheduler.py:54`, both *after* the lock is dropped at line 51.

Failure scenario (interleaving): worker pops job "x" (line 51, lock released) → worker evaluates `"x" in self._cancelled` → False (line 52) → thread switch → `cancel("x")`: `"x" in self._started` is False (line 37), so it adds "x" to `_cancelled` and returns `True` (lines 39-40) → worker resumes, adds "x" to `_started` (line 54) and calls `fn()` (line 55). `cancel` returned `True` but the job ran. G3 explicitly promises the opposite. For a cancel that means "don't charge the customer / don't send the email", the caller has been told the side effect was prevented when it was not.

Fix: the decision must be atomic with the pop. Take the lock in `cancel()`, and inside the worker's existing locked block (lines 44-51) do the `_cancelled` check and the `_started.add(job_id)` before releasing, so `cancel` can only ever observe a job as pending-or-started, never mid-transition.

### 4. `shutdown(wait=True)` returns while jobs are still running (High, G4)

`src/scheduler.py:68`: `t.join(timeout=5)`. The timeout is swallowed — no return value, no exception, no log.

Failure scenario: `submit("slow", lambda: time.sleep(10))`, then `shutdown(wait=True)`. After 5 s each `join` gives up, `shutdown()` returns, and the docstring's "no job may run after `shutdown()` returns" (`src/scheduler.py:10`) is false — the job runs for 5 more seconds. Because the threads are daemons (`src/scheduler.py:27`), a caller that exits the process right after `shutdown()` returns has the job torn down mid-write. `results()` also misses it. Fix: either join without a timeout, or take the timeout as a parameter and report unfinished workers to the caller (return `False` / raise `TimeoutError`) so the failure is distinguishable from success.

### 5. `_cancelled` is never cleared, so a reused `job_id` can never run again (Medium, G1)

`src/scheduler.py:39` adds to `_cancelled` and nothing ever removes from it; the worker's skip check on line 52 keys purely on `job_id`.

Failure scenario: a recurring id such as `"nightly-report"` is submitted daily. One night it is cancelled. Every subsequent `submit("nightly-report", ...)` is popped, matched against the stale `_cancelled` entry, and dropped on line 53 — silently, forever. No result, no log, no error. The same applies to `cancel()` for an id that was never submitted: it returns `True` and poisons that id pre-emptively. Both `_cancelled` and `_started` also grow without bound in a long-lived process. Fix: key cancellation on the unique `seq` (or a returned handle) rather than the caller-supplied `job_id`, and discard the entry when the job is popped.

## Hazards

- **Inconsistent lock discipline around `_done`/`_started`.** `src/scheduler.py:54,56` mutate shared state with no lock, while `results()` (`src/scheduler.py:59-60`) reads `_done` under the lock. Today this doesn't corrupt anything only because `list.append` and `set.add` are individually atomic under the GIL — it is correct by accident, not by design, and it is precisely the assumption that free-threaded/no-GIL builds remove. It also makes the lock in `results()` misleading, since it guards nothing the writer respects.
- **50 ms polling loop.** `src/scheduler.py:46` uses `wait(timeout=0.05)` in a loop, so N workers wake 20N times/sec while idle, and a correctly-notified job can still sit up to 50 ms. More importantly, this polling is what hides defect #1 — with a correct `notify()` the timeout should be unnecessary.
- **`submit()` after `shutdown()` is silently accepted.** `submit` (`src/scheduler.py:31`) never consults `_stop`. Depending on whether the drain loop has exited, the job either runs after shutdown or is dropped forever — nondeterministically, with no signal either way.

## Nit

- `src/scheduler.py:49-50` is dead code: exiting the `while` on line 45 implies `_heap` is non-empty or `_stop`, and the `_stop and not _heap` case already returned on line 48, so `if not self._heap: continue` can never be true.

## On "fix any defect you find"

I can't do that part in this session: this profile is read-only by instruction, and the sandbox enforces it (no `Write`/`Edit` tool; `Bash` and `Monitor` both return "recon mode is read-only: changes are blocked"). So **no fix has been applied and nothing was executed** — in particular I could not confirm defect #1 by running `tests/test_sanity.py`, though I expect that test to fail today at `tests/test_sanity.py:5`. Each finding above carries the precise fix; if you want them applied, re-run this task with a profile that has write access.

**Verdict:** Not shippable — `submit()` is broken on essentially every call (#1), and three of the four documented guarantees (G1, G3, G4) have concrete, reachable violations.