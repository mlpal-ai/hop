from src.scheduler import Scheduler

def test_runs_jobs():
    s = Scheduler(workers=2)
    s.submit("a", lambda: 1)
    s.submit("b", lambda: 2)
    s.shutdown(wait=True)
    assert sorted(s.results()) == [("a", 1), ("b", 2)]
