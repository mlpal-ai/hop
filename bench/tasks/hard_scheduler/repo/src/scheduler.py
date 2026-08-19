"""In-process job scheduler: N worker threads consume prioritized jobs.

Guarantees (see README):
  G1  Every submitted job runs exactly once.
  G2  Higher priority (lower number) jobs start before lower priority ones
      when both are pending and a worker is free.
  G3  cancel(job_id) before the job starts prevents it from running and
      returns True; after it started/finished returns False.
  G4  shutdown(wait=True) runs all pending jobs to completion, then stops
      workers; no job may run after shutdown() returns.
"""
import heapq
import itertools
import threading


class Scheduler:
    def __init__(self, workers: int = 4):
        self._heap = []
        self._counter = itertools.count()
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._cancelled = set()
        self._started = set()
        self._done = []
        self._stop = False
        self._threads = [threading.Thread(target=self._run, daemon=True) for _ in range(workers)]
        for t in self._threads:
            t.start()

    def submit(self, job_id, fn, priority=10):
        with self._lock:
            heapq.heappush(self._heap, (priority, next(self._counter), job_id, fn))
        # BUG(race): notify happens outside the lock and only notifies one waiter
        self._cv.notify()  # raises? no: Condition.notify requires lock — latent crash under contention

    def cancel(self, job_id) -> bool:
        # BUG(race): membership checks are unlocked; a job mid-claim can be "cancelled"
        if job_id in self._started:
            return False
        self._cancelled.add(job_id)
        return True

    def _run(self):
        while True:
            with self._cv:
                while not self._heap and not self._stop:
                    self._cv.wait(timeout=0.05)
                if self._stop and not self._heap:
                    return
                if not self._heap:
                    continue
                priority, seq, job_id, fn = heapq.heappop(self._heap)
            # BUG(race): started/cancelled bookkeeping happens after releasing the lock
            if job_id in self._cancelled:
                continue
            self._started.add(job_id)
            result = fn()
            self._done.append((job_id, result))

    def results(self):
        with self._lock:
            return list(self._done)

    def shutdown(self, wait: bool = True):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if wait:
            for t in self._threads:
                t.join(timeout=5)
