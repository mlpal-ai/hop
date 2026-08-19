import threading, time, random
from src.scheduler import Scheduler


def test_submit_never_crashes_and_all_run_once():
    s = Scheduler(workers=6)
    N = 300
    ran = []
    lock = threading.Lock()
    def mk(i):
        def fn():
            with lock: ran.append(i)
            return i
        return fn
    errs = []
    def submitter(base):
        try:
            for i in range(base, base + N // 6):
                s.submit(i, mk(i), priority=random.randint(1, 5))
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=submitter, args=(k * (N // 6),)) for k in range(6)]
    for t in ts: t.start()
    for t in ts: t.join()
    s.shutdown(wait=True)
    assert not errs, f"submit raised: {errs[:3]}"
    assert sorted(ran) == list(range(N)), "every job exactly once (G1)"
    assert len(s.results()) == N


def test_cancel_semantics_exclusive():
    for _ in range(15):
        s = Scheduler(workers=4)
        ran = set()
        lock = threading.Lock()
        def mk(i):
            def fn():
                with lock: ran.add(i)
            return fn
        ids = list(range(60))
        for i in ids:
            s.submit(i, mk(i))
        results = {}
        def canceller(sub):
            for i in sub:
                results[i] = s.cancel(i)
        cs = [threading.Thread(target=canceller, args=(ids[k::3],)) for k in range(3)]
        for c in cs: c.start()
        for c in cs: c.join()
        s.shutdown(wait=True)
        for i in ids:
            cancelled_ok = results.get(i, False)
            executed = i in ran
            assert cancelled_ok != executed, f"job {i}: cancel={cancelled_ok} ran={executed} (G3 exclusivity)"


def test_shutdown_drains_pending():
    s = Scheduler(workers=2)
    done = []
    lock = threading.Lock()
    def slow(i):
        def fn():
            time.sleep(0.01)
            with lock: done.append(i)
        return fn
    for i in range(40):
        s.submit(i, slow(i))
    s.shutdown(wait=True)
    assert len(done) == 40, "shutdown(wait=True) must drain pending jobs (G4)"


def test_priority_ordering_when_saturated():
    s = Scheduler(workers=1)
    order = []
    lock = threading.Lock()
    gate = threading.Event()
    def blocker():
        gate.wait(timeout=5)
    s.submit("block", blocker, priority=0)
    time.sleep(0.05)  # let the single worker claim the blocker
    def mk(i):
        def fn():
            with lock: order.append(i)
        return fn
    s.submit("low", mk("low"), priority=9)
    s.submit("high", mk("high"), priority=1)
    s.submit("mid", mk("mid"), priority=5)
    gate.set()
    s.shutdown(wait=True)
    assert order == ["high", "mid", "low"], f"priority order violated (G2): {order}"
