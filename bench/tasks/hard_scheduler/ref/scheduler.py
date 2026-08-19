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
        with self._cv:
            heapq.heappush(self._heap, (priority, next(self._counter), job_id, fn))
            self._cv.notify()

    def cancel(self, job_id) -> bool:
        with self._cv:
            if job_id in self._started or job_id in self._cancelled:
                return False
            self._cancelled.add(job_id)
            return True

    def _run(self):
        while True:
            with self._cv:
                while True:
                    while self._heap:
                        priority, seq, job_id, fn = heapq.heappop(self._heap)
                        if job_id in self._cancelled:
                            continue
                        self._started.add(job_id)
                        break
                    else:
                        if self._stop:
                            return
                        self._cv.wait(timeout=0.05)
                        continue
                    break
            result = fn()
            with self._cv:
                self._done.append((job_id, result))

    def results(self):
        with self._cv:
            return list(self._done)

    def shutdown(self, wait: bool = True):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if wait:
            for t in self._threads:
                t.join(timeout=10)
