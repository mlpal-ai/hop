I have the full picture: 51 lines of source, one sanity test covering only `balances`, and a README that makes no ordering promises the module doesn't already make itself.

**Note up front on "fix any defect":** this session is read-only recon mode — `Bash` is denied and I have no `Write`/`Edit` tool, so I could not apply or test a patch. The fixes below are described precisely but are **unapplied and unverified by execution**; verification was by reading. Flagging the capability mismatch rather than working around the sandbox.

## Findings

### D1 — High · `statement()` never sorts, so "chronological running balance" is wrong — `src/ledger.py:24-36`

The docstring at `src/ledger.py:22-23` states the contract twice: the result is a *"Chronological running balance"* and *"Lines are not guaranteed to be sorted by date"*. The implementation appends rows in file order (`src/ledger.py:30`) and accumulates in that same order (`src/ledger.py:33-35`). No sort ever happens.

Failure scenario:
```python
lines = ["2026-01-02,cash,-40.00", "2026-01-01,cash,100.00"]
statement(lines, "cash")
# actual:   [("2026-01-02", -40.0), ("2026-01-01", 60.0)]
# expected: [("2026-01-01", 100.0), ("2026-01-02", 60.0)]
```
The account is reported as overdrawn at −40.00 on Jan 2, and the dates come back descending. Note the *final* balance is coincidentally right (addition commutes), which is exactly why this hides in testing — every intermediate row is wrong, so any consumer doing an overdraft check, a minimum-balance check, or charting the series gets a false result.

Fix: sort by date before accumulating, in `statement`, after the collection loop:
```python
rows.sort(key=lambda r: r[0])   # ISO YYYY-MM-DD sorts lexicographically
```
`list.sort` is stable, so same-date entries retain their original file order — which is the only sensible tiebreak here since the format carries no intra-day sequence number.

### D2 — Medium-High · `monthly_totals()` returns first-appearance order, not chronological — `src/ledger.py:41-50`

`src/ledger.py:40` promises *"months in chronological order."* `OrderedDict` preserves **insertion** order, i.e. the order months first appear in the input. Per D1's own docstring the input is explicitly not guaranteed sorted, so insertion order ≠ chronological. The `OrderedDict` choice looks like it was mistaken for a sorted container.

Failure scenario:
```python
lines = ["2026-02-05,cash,50.00", "2026-01-10,cash,10.00"]
monthly_totals(lines, "cash")
# actual:   [("2026-02", 50.0), ("2026-01", 10.0)]
# expected: [("2026-01", 10.0), ("2026-02", 50.0)]
```
A caller taking `result[-1]` as "latest month" gets January instead of February — a silently wrong number on a reporting path, not a crash.

Fix: sort the keys on the way out. `return sorted(months.items())` (tuple ordering keys on the `YYYY-MM` string, which is chronological). Once sorted, `OrderedDict` earns nothing over a plain `dict` and should become one.

### H1 — Medium hazard · per-step rounding silently discards sub-cent amounts — `src/ledger.py:17`, `src/ledger.py:34`, `src/ledger.py:49`

All three accumulators round to 2dp on *every* step rather than once at the end. For amounts finer than a cent, each increment rounds away entirely.

```python
balances(["2026-01-01,cash,0.004"] * 1000)
# actual:   {"cash": 0.0}     each step: round(0.0 + 0.004, 2) == 0.0
# expected: {"cash": 4.0}
```
The input format at `src/ledger.py:2` places no precision constraint on `AMOUNT`, so sub-cent values (FX, interest accrual, unit pricing) are in-contract and vanish without any error. Related: `round()` is banker's rounding — `round(2.675, 2) == 2.67` — whereas money conventions normally want half-up.

I'd call this a hazard rather than a defect because today's only test and the README examples all use 2dp inputs, so nothing currently exercises it. Real fix is `decimal.Decimal` with an explicit `ROUND_HALF_UP` quantize at the boundary; the cheap mitigation is to accumulate unrounded and round once at return.

### H2 — Low hazard · `parse_line` raises context-free errors and accepts `nan`/`inf` — `src/ledger.py:6-8`

`parse_line` is the trust boundary (raw text → domain values) but validates nothing. A malformed line raises `ValueError: not enough values to unpack (expected 3, got 2)` with no indication of *which* line or file position — poor debuggability for a parser fed whole files. Separately, `float()` happily accepts `"nan"` and `"inf"`, and a single `nan` amount poisons an account balance to `nan` for every subsequent operation, comparing false against everything without raising. Worth wrapping to re-raise with the offending line included, and rejecting non-finite values.

### N1 — Nit · skip-blank/comment predicate triplicated — `src/ledger.py:14`, `src/ledger.py:26`, `src/ledger.py:43`

The same `if not line.strip() or line.lstrip().startswith("#"): continue` appears verbatim in all three public functions. Three copies to keep in sync; if comment syntax ever changes (inline `#`, for instance, which none of them currently handle) one will be missed. Extract a small `_records(lines)` generator that filters and parses, and have all three consume it.

## Coverage gap

`tests/test_sanity.py` has exactly one test, against `balances` only, with pre-sorted input — so both D1 and D2 are entirely uncovered, and `statement`/`monthly_totals` have zero tests. Any fix should land with an out-of-order-input regression test per function, since sorted input cannot distinguish correct from broken here.

## Verdict

Two real ordering defects (D1, D2) sharing one root cause — a missing sort in code whose own docstrings state the input is unsorted — both producing silently wrong numbers rather than errors; D1 is the one to fix first. Patch not applied: read-only session.