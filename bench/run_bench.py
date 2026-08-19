#!/usr/bin/env python3
"""Profile-split no-regression bench: published 0.8.0 vs dev build (engine+profiles).

4 fresh tasks x 2 harnesses x N=2 runs, serial (one gateway key, no rate-limit games).
Grading = the panel's hidden suites, run out-of-repo. Metrics: correct, wall seconds,
output tokens (sum of result-event usage), turns.
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

# python3 on this box is 3.14 without pytest — grade with an interpreter that has it,
# and refuse to start if none does (a grader that can't run marks everything false).
GRADER_PY = os.environ.get("GRADER_PY", "python3.13")
if subprocess.run([GRADER_PY, "-m", "pytest", "--version"], capture_output=True).returncode != 0:
    sys.exit(f"grader interpreter {GRADER_PY} has no pytest")

BASE = Path(__file__).parent
HARNESSES = {
    "npm-0.8.0": str(BASE / "oldbin/node_modules/.bin/yodex"),
    "dev-profiles": os.path.expanduser("~/.yodex-dev/yodex"),
}
TASKS = ["easy_ledger", "easy_slug", "hard_scheduler", "hard_ratelimit"]
RUNS = 2
OUT = BASE / "results"
OUT.mkdir(exist_ok=True)

def grade(task: str, repo: Path) -> bool:
    hidden = BASE / "tasks" / task / "hidden"
    work = repo.parent / "grade"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(repo, work)
    for d in work.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    for f in hidden.glob("test_*.py"):
        shutil.copy(f, work / f.name)
    r = subprocess.run(
        [GRADER_PY, "-m", "pytest", "-q", "--no-header", "-x", *[f.name for f in hidden.glob("test_*.py")]],
        cwd=work, capture_output=True, text=True, timeout=300,
    )
    return r.returncode == 0

def one_run(harness: str, binpath: str, task: str, run_i: int) -> dict:
    tag = f"{harness}__{task}__r{run_i}"
    work = BASE / "work" / tag
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    repo = work / "repo"
    shutil.copytree(BASE / "tasks" / task / "repo", repo)
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    prompt = (BASE / "tasks" / task / "prompt.txt").read_text()

    env = {**os.environ, "YODEX_MODEL": "claude-opus-5"}
    t0 = time.monotonic()
    with open(OUT / f"{tag}.jsonl", "w") as logf:
        p = subprocess.run(
            [binpath, "--json", "--cwd", str(repo), prompt],
            stdout=logf, stderr=subprocess.DEVNULL, env=env, timeout=2400,
        )
    wall = time.monotonic() - t0

    out_tok = in_tok = turns = 0
    status = "?"
    for line in open(OUT / f"{tag}.jsonl"):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            u = ev.get("usage", {})
            out_tok += u.get("output_tokens", 0)
            in_tok += u.get("input_tokens", 0)
            turns += ev.get("numTurns", 0)
            status = ev.get("subtype", "?")
    correct = grade(task, repo)
    rec = {
        "harness": harness, "task": task, "run": run_i, "correct": correct,
        "wall_s": round(wall, 1), "output_tokens": out_tok, "input_tokens": in_tok,
        "turns": turns, "exit": p.returncode, "status": status,
    }
    print(json.dumps(rec), flush=True)
    return rec

def selfcheck() -> None:
    """Two-way grader validation: the reference solution must PASS the hidden suite and
    the unmodified repo must FAIL it. A grader that can't tell them apart grades nothing."""
    for task in TASKS:
        tdir = BASE / "tasks" / task
        ref_files = list((tdir / "ref").glob("*.py"))
        # ref passes
        work = BASE / "work" / f"selfcheck_{task}"
        if work.exists():
            shutil.rmtree(work)
        repo = work / "repo"
        shutil.copytree(tdir / "repo", repo)
        for f in ref_files:
            dest = next(repo.rglob(f.name), None)
            assert dest, f"{task}: ref file {f.name} not found in repo"
            shutil.copy(f, dest)
        assert grade(task, repo), f"{task}: reference solution FAILS hidden suite — grader broken"
        # unmodified fails
        shutil.rmtree(work)
        shutil.copytree(tdir / "repo", repo)
        assert not grade(task, repo), f"{task}: unmodified repo PASSES hidden suite — no signal"
        print(f"selfcheck ok: {task}", flush=True)

def regrade_existing(harness: str, task: str, run_i: int) -> dict | None:
    """A completed run (log + work dir) whose grade was produced by the broken grader:
    re-grade the surviving repo instead of paying for a re-run."""
    tag = f"{harness}__{task}__r{run_i}"
    log = OUT / f"{tag}.jsonl"
    repo = BASE / "work" / tag / "repo"
    if not (log.exists() and repo.exists()):
        return None
    out_tok = in_tok = turns = 0
    status = None
    for line in open(log):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            u = ev.get("usage", {})
            out_tok += u.get("output_tokens", 0)
            in_tok += u.get("input_tokens", 0)
            turns += ev.get("numTurns", 0)
            status = ev.get("subtype", "?")
    if status is None:
        return None  # log has no result event — the run never finished; rerun it
    rec = {
        "harness": harness, "task": task, "run": run_i, "correct": grade(task, repo),
        "wall_s": None, "output_tokens": out_tok, "input_tokens": in_tok,
        "turns": turns, "exit": 0, "status": status, "regraded": True,
    }
    print(json.dumps(rec), flush=True)
    return rec

def main() -> None:
    selfcheck()
    results = []
    for task in TASKS:
        for harness, binpath in HARNESSES.items():
            for i in range(1, RUNS + 1):
                try:
                    results.append(regrade_existing(harness, task, i) or one_run(harness, binpath, task, i))
                except Exception as e:  # timeout etc. — record, keep going
                    rec = {"harness": harness, "task": task, "run": i, "correct": False,
                           "error": str(e)[:200]}
                    print(json.dumps(rec), flush=True)
                    results.append(rec)
                (OUT / "summary.json").write_text(json.dumps(results, indent=1))
    print("BENCH-DONE", flush=True)

if __name__ == "__main__":
    main()
