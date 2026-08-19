# No-regression benchmark: 0.8.0 vs the engine/profile split

Paired comparison of published yodex 0.8.0 (pre-split) against the profile-ized
build. Same pinned model (claude-opus-5), 4 contamination-free tasks (2 easy /
2 hard, authored for the five-harness panel with hidden test suites), N=2 per
cell, serial on one machine.

- `tasks/<task>/{repo,prompt.txt,hidden,ref}` — the task, its hidden suite, and
  the reference solution
- `run_bench.py` — the runner; validates the grader two-way (ref must PASS,
  unmodified repo must FAIL) before any run counts
- `results/summary.json` + `results/*.jsonl` — per-run metrics and full
  stream-json logs

Result: 8/8 correct on both builds. Full table and reading in PAPER.md §6.
