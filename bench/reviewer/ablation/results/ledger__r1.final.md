I read the whole module, its only test, and the README. No Bash — I couldn't execute pytest, so every trace below is manual against the code as written.

## Defects

### 1. `statement()` never sorts by date — running balances are wrong (high)

`src/ledger.py:24-36`. The docstring at `src/ledger.py:22-23` states the contract explicitly: *"Chronological running balance"* and *"Lines are not guaranteed to be sorted by date (ISO YYYY-MM-DD)."* The code appends rows in file order at `src/ledger.py:30` and accumulates in that same order at `src/ledger.py:33-35`. There is no sort anywhere in the function.

Failure scenario:

```python
statement(["2026-01-05,cash,100.00", "2026-01-01,cash,-50.00"], "cash")
# returns [("2026-01-05", 100.0), ("2026-01-01", 50.0)]
# correct  [("2026-01-01", -50.0), ("2026-01-05", 50.0)]
```

Both the ordering *and* the balance values are wrong. The Jan 1 overdraft (-50.00) is reported as a positive 50.00 balance — the exact condition a statement exists to reveal is inverted. Only the final row's value happens to be right (it equals the unordered total).

Fix: sort `rows` before accumulating. Python's sort is stable, so ISO date strings sort chronologically as plain strings and same-day entries keep file order:

```python
rows.sort(key=lambda r: r[0])   # insert between line 30's loop and line 31
```

### 2. `monthly_totals()` returns months in first-appearance order, not chronological (medium)

`src/ledger.py:39-50`. The docstring at `src/ledger.py:40` promises *"months in chronological order"*, but `OrderedDict` at `src/ledger.py:41` preserves **insertion** order, i.e. the order months first appear in the input. Same unsorted-input premise as defect 1 — the module's own docstring at `src/ledger.py:23` says input isn't date-sorted.

Failure scenario:

```python
monthly_totals(["2026-02-01,cash,5.00", "2026-01-15,cash,3.00"], "cash")
# returns [("2026-02", 5.0), ("2026-01", 3.0)]
# correct  [("2026-01", 3.0), ("2026-02", 5.0)]
```

The per-month sums are correct; only the ordering breaks. Any consumer plotting or diffing month-over-month gets a scrambled series.

Fix: `return sorted(months.items())` at `src/ledger.py:50`. `YYYY-MM` keys sort lexicographically = chronologically. That also makes `OrderedDict` pointless — a plain `dict` suffices (`src/ledger.py:3` import becomes dead).

## Hazards

### 3. Zero test coverage on both broken functions

`tests/test_sanity.py:1-5` imports and exercises only `balances`. `statement` and `monthly_totals` — the two functions with order-dependent contracts, and the only two that are wrong — have no tests at all. That's why both bugs survived. Any fix should land with a test feeding deliberately out-of-order lines.

### 4. Floats for money, with per-step rounding

`src/ledger.py:17`, `src/ledger.py:34`, `src/ledger.py:49` all do `round(acc + amount, 2)` on binary floats. Correct for the two-decimal inputs in the README's format, but `round()` is banker's rounding over values that aren't exactly representable, so sub-cent inputs round unpredictably. Note also that fixing defect 1 changes the *order* of the rounding steps in `statement`, so its final row can now differ from `balances()` by a cent on pathological inputs. `decimal.Decimal` or integer cents is the durable answer. Not a defect against the stated input domain.

### 5. Unvalidated parse at the trust boundary

`src/ledger.py:7`: `[p.strip() for p in line.split(",")]` unpacked into exactly three names. A line with an extra comma (a memo field, a trailing comma, an account name containing a comma) raises a bare `ValueError: too many values to unpack (expected 3)` with no line number or content. Same for a non-numeric amount at `src/ledger.py:8`. Failing loudly is right; failing anonymously on a 10k-line file is not.

### 6. Triplicated skip predicate

`src/ledger.py:14`, `src/ledger.py:26`, `src/ledger.py:43` are byte-identical blank/comment filters. Three places to forget when the comment character or blank-line rule changes. A shared `_records(lines)` generator would collapse all three loops.

## On "fix any defect"

I could not apply the fixes. This profile is read-only recon: `Bash` returns `Permission denied: recon mode is read-only: changes are blocked`, and I have no write or edit tool. Defects 1 and 2 are each a one-line change, specified exactly above (`rows.sort(key=lambda r: r[0])` after `src/ledger.py:30`; `sorted(...)` at `src/ledger.py:50`). Both are unapplied and untested by me — please apply them, and add an out-of-order-input test for each, since `tests/test_sanity.py` would pass unchanged either way.

**Verdict:** Two real ordering defects, both directly contradicting the functions' own docstrings; `statement()` is the serious one because it reports wrong balance values, not merely wrong order.