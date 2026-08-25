I have the full picture: 51 lines of source, one sanity test covering only `balances`, and no other callers in the repo.

Note up front: **this profile is read-only** — `Bash` is blocked ("recon mode is read-only") and I have no edit tool, so I could not run `pytest` and I cannot apply the fixes. Findings below are from static tracing; I've hand-executed each scenario against the code. I describe the exact fix for each, unapplied.

---

## Defects

### 1. `statement()` ignores date ordering despite promising chronological output — HIGH
`src/ledger.py:21-36`. The docstring at `src/ledger.py:22-23` states the contract twice: *"Chronological running balance"* and *"Lines are not guaranteed to be sorted by date (ISO YYYY-MM-DD)."* The code never sorts. `rows` is built in input order at `src/ledger.py:30`, and the accumulation loop at `src/ledger.py:33-35` walks that same input order. The split into two loops (`src/ledger.py:24-30` then `31-35`) is exactly where a sort belongs and is otherwise pointless — the collect step exists solely to be sorted, and isn't.

Failure scenario:
```python
lines = ["2026-01-03,cash,-100.00",
         "2026-01-01,cash,50.00",
         "2026-01-02,cash,70.00"]
statement(lines, "cash")
```
Returns `[("2026-01-03", -100.0), ("2026-01-01", -50.0), ("2026-01-02", 20.0)]`.
Correct result: `[("2026-01-01", 50.0), ("2026-01-02", 120.0), ("2026-01-03", 20.0)]`.

Two distinct harms: the rows are emitted in non-date order (so any UI rendering the statement shows time running backwards), and every running balance is numerically wrong. The account never actually went below zero, yet the statement reports a -100.00 overdraft on the first row — an overdraft-detection or minimum-balance check reading this output fires a false alarm. Only the *final* value happens to be right, because addition is order-independent.

Fix: sort `rows` by date before accumulating — insert `rows.sort(key=lambda r: r[0])` between `src/ledger.py:30` and `31`. ISO `YYYY-MM-DD` sorts correctly as a string, and Python's sort is stable, so multiple transactions on the same date retain input order.

### 2. `monthly_totals()` returns months in first-appearance order, not chronological — HIGH
`src/ledger.py:39-50`. The docstring at `src/ledger.py:40` promises *"months in chronological order."* `OrderedDict` at `src/ledger.py:41` preserves **insertion** order — the order each month is first seen in the input — and `src/ledger.py:50` returns that directly. Since the input is explicitly not guaranteed sorted (`src/ledger.py:23`), insertion order is not chronological order.

Failure scenario:
```python
lines = ["2026-02-01,cash,10.00",
         "2026-01-15,cash,5.00"]
monthly_totals(lines, "cash")
```
Returns `[("2026-02", 10.0), ("2026-01", 5.0)]`. Correct: `[("2026-01", 5.0), ("2026-02", 10.0)]`.

The per-month sums are right; only the sequence is wrong. That makes it a nasty one — a caller plotting a time series or computing month-over-month deltas gets a chart with the x-axis scrambled and a delta with the wrong sign, with no exception to signal it.

Fix: return `sorted(months.items())` at `src/ledger.py:50`. `YYYY-MM` keys sort chronologically as strings. Once sorted, `OrderedDict` earns nothing over a plain `dict` and the `collections` import at `src/ledger.py:3` can go.

---

## Hazards

### 3. `parse_line()` raises an uninformative `ValueError` on any malformed line — MEDIUM
`src/ledger.py:7`. The unpack `date, account, amount = [...]` requires exactly three comma-separated fields, and `float(amount)` at `src/ledger.py:8` requires a numeric third field. Neither is guarded, and none of the three callers (`src/ledger.py:16`, `28`, `45`) catch anything.

Failure scenario: a line `"2026-01-01,office,supplies,-12.00"` (a comma inside an account name — the format has no quoting or escaping) raises `ValueError: too many values to unpack (expected 3)`. The traceback names `parse_line` but not the offending line or its line number, so operating on a 10k-line file gives no way to locate the bad record without bisecting by hand. Same class of failure for a truncated line (`"2026-01-01,cash"`) or a non-numeric amount.

This is at a trust boundary — the input is a text file, not internal code — so validation belongs here. Minimum fix: raise `ValueError(f"malformed line: {line!r}")` from `parse_line`, and have callers include the enumeration index. Left as-is, the format's ambiguity around commas in account names remains undocumented in `README.md:2`.

### 4. Money held as binary floats — LOW
`src/ledger.py:8` parses to `float`; `src/ledger.py:17`, `34`, `49` accumulate and `round(..., 2)` at each step. The per-step rounding does contain drift for well-formed 2-decimal inputs, so this is not currently producing wrong totals. But `round()` is banker's rounding (`round(2.675, 2) == 2.67`), and because rounding happens *per step* rather than once at the end, results become dependent on transaction order — which interacts badly with the sort fix in #1: adding the sort can legitimately change a reported cent. `Decimal` is the standard primitive for currency here. Flagging so the ordering fix doesn't get blamed for an unrelated cent shift.

### 5. Skip-blank/comment logic triplicated — NIT
`src/ledger.py:14`, `26`, `43` are byte-identical. Three copies of a parsing rule that must stay in sync; a fourth entry point will forget one. Folding the filter into a shared generator (or into `parse_line` returning `None`) removes the drift risk.

---

## Test coverage gap (root cause)

`tests/test_sanity.py:1-5` imports and exercises **only** `balances`. `statement` and `monthly_totals` have zero coverage — which is precisely why defects #1 and #2 are sitting in the tree. Both are trivially testable with the unsorted-input scenarios above, and both docstrings already state the contract the tests should assert.

---

## Verdict

Two real defects, both the same root cause — `statement` (`src/ledger.py:21-36`) and `monthly_totals` (`src/ledger.py:39-50`) each promise chronological output in their docstrings and neither sorts, so any input that isn't already date-sorted produces wrong running balances and a scrambled month series. **The fixes are described but not applied: this session is read-only, so I could not edit the file or run the test suite to confirm.** Worth flagging as a capability mismatch — the "fix any defect" half of the request needs a profile with write access.