# H2 policy-transfer campaign: the reviewer HOP

Eight headless runs (4 seeded-defect repos x N=2, claude-opus-5) of the builtin
`reviewer` HOP under prompts that explicitly request fixes. Answer-leaking `# BUG`
comments are stripped by the runner; defects are behavioral only.

- `run_rev.py` — the runner (resume-safe; strips leak comments; measures mutations,
  audit blocks, tokens, wall)
- `results/*.rec.json` — per-run measures
- `results/*.final.md` — each run's delivered review (detection graded against
  `../tasks/*/ref` diffs)
- `results/*.jsonl` — full stream-json transcripts, including every fail-closed
  audit refusal

Reported in the paper (Table 2): 8/8 seeded-defect detection, 0 tracked-file
changes, 0 Write/Edit calls, 13 substantive audit refusals; 5/8 explicit audit
PASS, 3/8 delivered at the continuation cap with refusals visible. Campaign 1
(pre-fix) caught the verifier-deliverable seam bug described in the paper §4.2;
its runs are superseded by this post-fix campaign under identical measures.
