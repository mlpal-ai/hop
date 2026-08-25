On-disk source is unchanged, and `Bash` is still refused — I cannot execute or edit. Corrected review below; I've dropped the two findings the verifier refuted, re-anchored the rest, and made explicit the one fact that changes several traces: **`heapq.heappush` at line 33 completes before the `RuntimeError` at line 34, so a job is enqueued and will run even though `submit()` raised.** Every scenario below is written against the code as it stands.

## Defects (present, current behavior)

### 1. CRITICAL — `submit()` raises `RuntimeError` on every call: `notify()` is outside the lock
`src/scheduler.py:32-34`

```python
with self._lock:                       # 32
    heapq.heappush(...)                # 33  12-space indent, inside
self._cv.notify()                      # 34   8-space indent, OUTSIDE
```

`self._cv` wraps `self._lock` (line 22). `Condition.notify()` begins `if not self._is_owned(): raise RuntimeError("cannot notify on un-acquired lock")`, and the lock was released when the `with` block closed at line 33.

Failure scenario, current code: `s = Scheduler(workers=2); s.submit("a", lambda: 1)` → `RuntimeError: cannot notify on un-acquired lock` propagates to the caller. `tests/test_sanity.py:5` fails on the first `submit`. The suite is red today.

Two consequences worth separating, because they drive the other findings:

- **The job still runs.** The push at 33 already mutated `_heap`, so the caller gets an exception for a job that is nonetheless queued and executed. Callers cannot treat the exception as "not submitted."
- **No worker is ever notified, for any job.** Since every `notify()` raises, the only thing that wakes a worker is the `wait(timeout=0.05)` poll at line 46. The condition variable is dead weight and every job pays up to 50 ms of queuing latency.

Fix: dedent-in line 34 so `notify()` executes inside the `with self._lock:` block.

### 2. HIGH — an unhandled exception in a job permanently kills the worker thread (violates G1)
`src/scheduler.py:55`, loop body `src/scheduler.py:43-56`

`result = fn()` is unguarded and nothing in `_run` catches. An exception escapes the thread target, `threading.excepthook` prints a traceback, and that worker is gone for the life of the process.

Failure scenario, current code (no fix to #1 required):

```python
s = Scheduler(workers=1)
for jid, fn in (("bad", lambda: 1/0), ("good", lambda: 1)):
    try: s.submit(jid, fn)
    except RuntimeError: pass      # defect #1; both jobs are on the heap regardless
s.shutdown(wait=True)
s.results()                        # []
```

Both entries are on the heap (pushed at line 33). Equal priority, so seq ordering pops `"bad"` first; `1/0` kills the only worker at line 55. `"good"` stays on the heap forever. `shutdown(wait=True)` joins an already-dead thread, returns instantly and successfully, and `results()` is empty. G1 is violated and `shutdown` gives the caller no way to distinguish this from a clean drain. With N workers, N failing jobs drain the pool to zero.

Fix: wrap lines 52-56 in `try/except BaseException as exc:` and record the failure (e.g. append to a `_failed` list) then `continue`. The worker loop must not be able to exit via exception.

### 3. HIGH — `cancel()` races the start marker and can return `True` for a job that runs (violates G3)
`src/scheduler.py:36-40` and `src/scheduler.py:52-55`

`cancel()` reads `_started` (37) and writes `_cancelled` (39) with no lock. The worker reads `_cancelled` (52) and writes `_started` (54) with no lock, and both are outside the critical section that ends at line 51.

Failure scenario: two threads, job `"j"` popped by a worker.

| worker | caller |
|---|---|
| 52: `"j" not in _cancelled` → falls through | |
| *(GIL switch — 52 and 54 are separate bytecode steps with no lock held)* | |
| | 37: `"j" not in _started` → does not return False |
| | 39: `_cancelled.add("j")`; 40: **returns `True`** |
| 54: `_started.add("j")`; 55: `fn()` runs | |

G3 states a `True` return means the job is prevented from running. Here the caller is told the charge/email/write was cancelled and it executes anyway. The window is narrow (a few bytecodes) but unguarded, so it is reachable under load or with a reduced `sys.setswitchinterval`; it is exactly the kind of failure that never reproduces in the single-threaded sanity test.

Fix: hold `self._lock` in `cancel()`, and move the `_cancelled` check and `_started.add` up into the same critical section as the `heappop` (lines 51-54). `fn()` at 55 must be the only part outside the lock.

### 4. MEDIUM-HIGH — `shutdown(wait=True)` returns while a job is still executing (violates G4)
`src/scheduler.py:66-68`

`t.join(timeout=5)`; the return value is discarded and `shutdown` returns unconditionally. G4: "no job may run after `shutdown()` returns."

Failure scenario, current code:

```python
s = Scheduler(workers=1)
try: s.submit("slow", lambda: time.sleep(10))
except RuntimeError: pass          # defect #1; job is queued at line 33 anyway
t0 = time.monotonic()
s.shutdown(wait=True)              # returns at t0+5, worker still inside fn()
```

At return, the worker is alive and mid-`fn()`. The caller proceeds to tear down resources the job is still using, and because the threads are `daemon=True` (line 27) interpreter exit will kill the job mid-flight rather than let it finish. Two aggravating factors on the same line: the timeout is per-thread, so the worst case is `5 * workers` seconds, and a timed-out join is completely silent.

Fix: `t.join()` with no timeout, or keep a bound and check `t.is_alive()` afterwards, raising/returning a "did not drain" signal.

## Hazards (not currently observable failures)

- **`submit()` after `shutdown()` — latent, becomes a defect once #1 is fixed.** `src/scheduler.py:31-34` never checks `self._stop`. *Today* the caller does get an exception (the line-34 `RuntimeError`), so this is not a silent acceptance — my earlier characterization was wrong. Once #1 is fixed, `submit()` after all workers have returned via line 48 will succeed, push onto `_heap`, and the job will never run, with no error to the caller. Fix alongside #1: `if self._stop: raise RuntimeError(...)` inside the `with` block in `submit`.
- **`_done` appended without the lock `results()` takes.** `src/scheduler.py:56` vs `59-60`. `list.append` and `list(...)` are individually atomic under CPython's GIL, so there is no present misbehavior — this is not a defect today. What it is: the `with self._lock` in `results()` excludes only other readers and protects nothing, which misleads the next maintainer. It becomes real only if line 56 ever grows into a read-modify-write.
- **`cancel()` on a not-yet-submitted id silently drops the later job.** `s.cancel("x")` returns `True` (line 40) with `"x"` unknown; a subsequent `submit("x", fn)` is dropped at line 52 and never runs, with no error. Deterministic in current code. Whether this is a defect depends on intended semantics for cancelling an unknown id — the docstring's G3 doesn't say, so this needs a product decision, not necessarily a code change.
- **`_started` and `_cancelled` are never pruned** (`src/scheduler.py:23,24,39,54`): one retained id per completed job and per cancel, for the lifetime of the object. Source-supported, but no stated lifetime policy exists, so I can't call it a defect — flagging it as a design question for a long-lived scheduler.
- **Workers are started in `__init__` and poll every 50 ms** (`src/scheduler.py:27-29,46`). A `Scheduler` that is constructed and never shut down keeps N threads waking 20×/second until process exit; there is no finalizer, so dropping the last reference does not stop them. They are daemon threads and `shutdown()` does stop them cleanly — my earlier "unkillable" was wrong. I withdraw the failed-`__init__` claim entirely; I have no concrete scenario for it.

## Nits

- `src/scheduler.py:49-50` — dead code. After the loop at 45 exits, either `_heap` is non-empty or `_stop` is set, and the `_stop and empty` case already returned at 48.
- `src/scheduler.py:51` — `priority` and `seq` are unpacked and never used.
- `tests/test_sanity.py` — exercises only the happy path of G1: no priority-ordering test (G2), no cancel test (G3), no post-shutdown or long-job test (G4), and no job-raises test. Defects #2, #3 and #4 have no coverage.

## Withdrawn from my previous review

- "post-shutdown submit is silently accepted and lost with no error" — wrong about current behavior; `submit` raises. Restated above as a latent issue conditional on fixing #1.
- "unlocked `_done` append is a MEDIUM defect" — no present failing outcome; demoted to a hazard about a misleading lock.
- "`notify()` vs `notify_all()` is fragile" — dropped; I have no missed-wakeup trace, and one notify per queued job is sufficient. The real, provable point (no notification ever fires) is folded into #1.

## Fixes: not applied

I could not apply any of this. This session is the read-only reviewer profile: there is no edit/write tool, and `Bash` is refused with `Permission denied: recon mode is read-only: changes are blocked` (re-confirmed just now, twice). **No file has been modified and none of the fixes above have been run or tested.** The minimal correct shape is: `notify()` inside the lock in `submit` plus a `_stop` rejection there; pop + cancelled-check + `_started.add` in one critical section in `_run`; `cancel()` under that same lock; `fn()` the only work outside the lock, wrapped in `try/except BaseException`; and an untimed `join()` in `shutdown`.

If the verifier is checking the working tree for an applied patch, this loop cannot converge from here — re-run the task with a write-capable profile.

**Verdict: not shippable.** `submit()` raises on every call (#1), and jobs still execute despite that exception, which leaves G1 (#2), G3 (#3) and G4 (#4) all violable in the code as it stands.