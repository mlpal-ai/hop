## Retractions

- **Retracted as false: "the repo is exactly three files" / "no dotfile."** My Glob for `**/.*` returned no matches and I read that as a filesystem fact. Wrong inference: Glob filters gitignored and VCS paths, so its silence proves nothing about the working tree — which does contain `.git/` and `.pytest_cache/`. The defensible claim is narrower: the **tracked project files** are `README.md`, `src/ledger.py`, `tests/test_sanity.py`, and none of them is a dependency manifest.
- **Retracted as unverifiable: intent claims.** "The `OrderedDict` import makes the bug read as deliberate" and "the two-pass shape is the tell" both assert what an author meant. Source code can't establish that. Replaced below with the mechanical facts only.
- **Reframed: same-day ordering.** I called stable input order "the only defined behavior." No repository contract defines same-day ordering — that was my proposed policy stated as fact. Reframed as a recommendation requiring a documented decision.
- **Tool-state is not review evidence.** My remarks about being unable to run commands or write files describe my session, not this repository, and I should not have placed them among findings. Addressed once at the end as an escalation, not a finding.

## Findings

### 1. DEFECT (high) — `statement` never sorts, violating its own docstring
`src/ledger.py:24-36`

Docstring promises a *"Chronological running balance"* and states *"Lines are not guaranteed to be sorted by date (ISO YYYY-MM-DD)"* (`src/ledger.py:22-23`). Rows are appended in input order (`src/ledger.py:30`) and consumed in that same order (`src/ledger.py:33-35`); no sort exists anywhere in the function.

Mechanically, `rows` is populated and then traversed once with no intervening transformation, so the intermediate list has no effect on the result — `src/ledger.py:31` is the only point where a reordering could apply.

```python
statement(["2026-01-03,cash,-50.00", "2026-01-01,cash,100.00"], "cash")
# returns [("2026-01-03", -50.0), ("2026-01-01", 50.0)]
# correct [("2026-01-01", 100.0), ("2026-01-03", 50.0)]
```
Both row order and balance-after values are wrong: the output reports `-50.00` on an account never overdrawn. The final row's value is correct only because addition commutes, so the error is confined to intermediate rows — the ones a statement exists to show.

### 2. DEFECT (high) — `monthly_totals` returns first-seen order, not chronological
`src/ledger.py:40-50`

Docstring promises *"months in chronological order"* (`src/ledger.py:40`). `OrderedDict` (`src/ledger.py:41`) preserves insertion — first-encounter — order, and `src/ledger.py:50` returns it directly. On Python 3.7+ a plain `dict` orders identically, so the import supplies no guarantee relevant to the promise.

```python
monthly_totals(["2026-02-01,cash,5.00", "2026-01-15,cash,10.00"], "cash")
# returns [("2026-02", 5.0), ("2026-01", 10.0)]   # February before January
# correct [("2026-01", 10.0), ("2026-02", 5.0)]
```
Per-month sums are correct; only sequence is wrong, so a caller taking deltas between adjacent entries inverts the trend's sign.

### 3. DEFECT (medium) — `parse_line` admits non-finite amounts; malformed lines fail without context
`src/ledger.py:7-8`

`float()` accepts `"nan"`/`"inf"`/`"-inf"`, so `balances(["2026-01-01,cash,nan"])` returns `{"cash": nan}` — a non-money token admitted as a balance with no error and no signal. The same value flows into `src/ledger.py:34` and `src/ledger.py:49`. Consumer impact is a prediction (no in-repo callers); what's evidenced is silent admission at the boundary.

The unguarded 3-way unpack at `src/ledger.py:7` also raises a bare `ValueError` (`not enough`/`too many values to unpack`) for any line with two or four fields — trailing comma, comma inside an account name, truncated final line — carrying no line number or offending text.

### 4. OBSERVATION (low) — per-transaction rounding diverges from final rounding for sub-cent inputs
`src/ledger.py:17,34,49`

Each function re-rounds the running total per transaction. Two `1.005` entries yield `2.0`, whereas `round(1.005 + 1.005, 2)` is `2.01`. Not general to all >2-decimal inputs — two `0.005` entries yield `0.01` either way. No contract in this repo (`README.md:2-3`, `src/ledger.py:1-2`) admits sub-cent amounts, so this stays an observation pending a stated precision contract.

### 5. OBSERVATION (low) — documented test command has no declared dependency
`README.md:3`

README instructs `python -m pytest`, but no tracked project file declares or pins `pytest`. A fresh clone cannot run the documented command without out-of-band setup.

### 6. NIT — skip predicate triplicated
`src/ledger.py:14`, `src/ledger.py:26`, `src/ledger.py:43`

Byte-identical at all three sites; no behavioral impact.

### Coverage gap
`tests/test_sanity.py:1-5` imports and invokes only `balances`, so neither `statement` nor `monthly_totals` — and neither ordering defect — is covered.

## Fixes (specified, not applied)

- **#1** — at `src/ledger.py:31`: `rows.sort(key=lambda r: r[0])`. ISO `YYYY-MM-DD` sorts lexicographically = chronologically, so no date parsing is needed. A stable sort keeps same-date rows in input order; since no repository contract defines same-day ordering, that tie-break should be chosen deliberately and written into the docstring.
- **#2** — `src/ledger.py:50` → `return sorted(months.items())`; replace `OrderedDict` with a plain `dict` and drop the `src/ledger.py:3` import. Same lexicographic argument applies to `YYYY-MM` keys.
- **#3** — at `src/ledger.py:8`, reject non-finite values (`math.isfinite`) and raise with the offending line content and index.
- **Tests** — add cases that *call* `statement` and `monthly_totals` with unsorted input; amending the existing fixture is insufficient, since that test never invokes either function.

## Escalation

I could not apply these fixes: this reviewer profile exposes no write tool, and shell execution is denied, so the working tree still contains no patch. That is a capability mismatch with the "fix any defect" part of the request, not a judgment that the fixes are wrong or unclear — and I'm flagging it rather than working around the sandbox. Re-running this task in a write-capable session will land the three one-line changes plus tests; each is specified above precisely enough to apply directly.

**Verdict:** two confirmed ordering defects, each contradicting its own docstring and both uncovered by the existing test; one confirmed boundary defect admitting non-finite amounts; float precision, the undeclared test dependency, and predicate duplication are observations. Fixes are specified but unapplied — a write-capable session is required to land them.