Read-only session — I could not run tests or apply a patch (`Bash` is blocked in this mode). Findings below are from static reading of `src/slug.py:1-23`, `tests/test_sanity.py:1-7`, `README.md`.

## Defects

### 1. `slugify` never transliterates accented characters — it mangles them into hyphens (High)

`src/slug.py:6-8` states the contract explicitly: *"Accented latin letters must transliterate to their ASCII base (café -> cafe); characters with no ASCII base are dropped."*

`src/slug.py:9-11` implements no transliteration at all. `str.lower()` leaves `é` as `é`, and `re.sub(r"[^a-z0-9]+", "-", s)` (`src/slug.py:10`) treats every non-ASCII codepoint as a separator, not as a droppable/mappable character.

Failure scenario — any title with a Latin-1 accent:

| input | actual | contract |
|---|---|---|
| `"Café"` | `"caf"` | `"cafe"` |
| `"Café Latte"` | `"caf-latte"` | `"cafe-latte"` |
| `"Ünïcôdé"` | `"n-c-d"` | `"unicode"` |
| `"Zoë"` | `"zo"` | `"zoe"` |
| `"Crème Brûlée"` | `"cr-me-br-l-e"` | `"creme-brulee"` |

Concretely: publishing "Café Culture in Paris" and "Caf Culture in Paris" both yield `caf-culture-in-paris`, so `unique_slug` (`src/slug.py:14`) silently appends `-2` to the second article — two distinct titles get URL-collided, and the accented one gets a truncated, meaningless slug that is not recoverable from the URL. For a French/Spanish/German title set this is not an edge case, it's the common path.

This is the only behavioral defect, and it is completely untested: `tests/test_sanity.py:4` and `:7` use pure-ASCII inputs, so the suite is green while the documented contract is violated.

**Fix** (not applied — read-only): normalize to NFKD and strip non-ASCII before the character-class pass.

```python
import re
import unicodedata


def slugify(title: str) -> str:
    ascii_title = (
        unicodedata.normalize("NFKD", title)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    s = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower())
    return s.strip("-")
```

NFKD decomposes `é` → `e` + U+0301; `encode("ascii", "ignore")` drops the combining mark and any codepoint with no ASCII base, satisfying both halves of the docstring. Keep the `.lower()` after the ASCII fold so `É` → `E` → `e`.

One behavior change worth a deliberate decision before merging: characters with no ASCII base currently act as word separators, after the fix they vanish. `"hello 世界 world"` → `"hello-world"` today (the surrounding spaces still separate), but `"hello世界world"` → `"hello-world"` today vs `"helloworld"` after. The docstring says "dropped", so the new behavior is the specified one — just confirm that's intended for CJK titles, which would otherwise collapse to `""` and fall through to `"untitled"` at `src/slug.py:16`.

## Hazards (correct today, fragile)

### 2. `unique_slug` is a TOCTOU check if `existing` is backed by a database (Medium)

`src/slug.py:16-22` reads `existing` and returns a candidate, but nothing reserves it. Two concurrent publishes of the same title both see `hello` free, both return `hello`, and the second insert fails on the unique index (or, without one, produces a duplicate). The function's docstring promises uniqueness it cannot enforce. Either document it as advisory-only, or make the caller retry on unique-constraint violation with the returned value fed back into `existing`.

### 3. No type annotation on `existing`, and membership cost is unbounded (Low)

`src/slug.py:14` annotates `title: str` but leaves `existing` bare. The hot loop at `src/slug.py:20` does repeated `in` checks; with a `list` (which the signature permits) the collision path is O(n·k) instead of O(k). Annotate as `collections.abc.Container[str]` and document that an O(1)-membership container is expected.

### 4. Non-`str` input fails with a bare `AttributeError` (Low)

`src/slug.py:9` calls `title.lower()` directly. `slugify(None)` — plausible from an optional DB column — raises `AttributeError: 'NoneType' object has no attribute 'lower'` from inside the slug module rather than a validated error at the boundary. Only worth handling if this is a boundary-facing entry point.

## Test gap

`tests/test_sanity.py` has no case for the transliteration clause, no empty/symbols-only case (`slugify("!!!")` → `""` → `"untitled"` via `src/slug.py:16`), and no multi-collision case (`existing={"hello","hello-2"}` → `"hello-3"`). Defect #1 would have been caught by a single `assert slugify("Café") == "cafe"`.

**Verdict:** one real defect — `slugify` violates its own documented transliteration contract at `src/slug.py:9-11`, silently truncating and colliding any accented title; fix is the NFKD fold above, which I could not apply or test in this read-only session.