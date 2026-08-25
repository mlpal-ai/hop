Dropping Hazard 3 and Nit 4 — the verifier is right that both are speculation about code that doesn't exist in this repo, with no present-day failure. Revised review below contains only what survives.

Also correcting the weak part of finding 2's remedy: a type annotation documents the invariant but doesn't enforce it, so the fix must materialize the argument at runtime.

## Defects

### 1. `slugify` does not transliterate accented latin letters — violates its documented contract (high)

`src/slug.py:9-11`. The only normalization is `title.lower()` at `src/slug.py:9`; the character class at `src/slug.py:10` is `[^a-z0-9]+`, so every non-ASCII code point is treated as a separator and collapsed to a hyphen. The docstring at `src/slug.py:7-8` explicitly promises `café -> cafe`.

Verified evaluations:

| input | actual | documented |
|---|---|---|
| `"Café Life"` | `caf-life` | `cafe-life` |
| `"Crème Brûlée"` | `cr-me-br-l-e` | `creme-brulee` |
| `"Ménage"` | `m-nage` | `menage` |
| `"İstanbul"` | `i-stanbul` | `istanbul` |

Failure scenario with a bad outcome inside this file: `"Ménage"` and `"M nage"` are distinct titles that both slugify to `m-nage`, so `unique_slug` (`src/slug.py:17`) sees a collision that shouldn't exist and suffixes the second one `m-nage-2`. Separately, `"Café"` → `caf` truncates a word rather than dropping a diacritic, and the caller cannot recover the intended text.

Fix — normalize to NFKD and drop non-ASCII *before* the separator pass, so decomposed diacritics disappear instead of becoming hyphens:

```python
"""URL slug generation for article titles."""
import re
import unicodedata


def slugify(title: str) -> str:
    """Lowercase ASCII slug: words joined by single hyphens, no leading/trailing
    hyphens. Accented latin letters must transliterate to their ASCII base
    (café -> cafe); characters with no ASCII base are dropped."""
    s = unicodedata.normalize("NFKD", title.lower())
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")
```

NFKD rather than NFD so compatibility forms fold too (`ﬁ` → `fi`, `²` → `2`). `lower()` must stay on the input to `normalize`, before the ASCII strip.

Note the fix leaves letters with no canonical decomposition dropped, not transliterated: `"Straße"` → `strae`, `"Łódź"` → `odz`. That is consistent with the docstring's "characters with no ASCII base are dropped" clause at `src/slug.py:8`, but it is the kind of thing worth pinning in a test so the behavior is a decision rather than an accident. If `ß`→`ss` is wanted, add an explicit pre-map before `normalize`.

Regression tests to add alongside `tests/test_sanity.py:4`: `slugify("Café Life") == "cafe-life"`, `slugify("Crème Brûlée") == "creme-brulee"`, `slugify("İstanbul") == "istanbul"`, `slugify("北京") == ""`, `unique_slug("北京", set()) == "untitled"` (exercises the fallback at `src/slug.py:16`).

## Hazards

### 2. `unique_slug` scans `existing` twice and returns a colliding slug when given a one-shot iterator (medium)

`src/slug.py:14,17,20`. `existing` is unannotated and consumed twice — once at `src/slug.py:17`, again in the loop at `src/slug.py:20`. A set (as in `tests/test_sanity.py:7`) is fine; any generator or iterator is not.

Verified failure: `unique_slug("Hello", iter(["hello-2", "hello"]))` returns `"hello-2"` — a value the caller listed as already taken. Line 17 exhausts the iterator finding `"hello"`, line 20 then scans an empty stream. No exception; a duplicate slug is silently emitted.

Fix must enforce, not merely document — materialize once at the boundary:

```python
def unique_slug(title: str, existing: Iterable[str]) -> str:
    """slugify(), then ensure uniqueness against `existing` by appending -2, -3, ..."""
    taken = frozenset(existing)
    base = slugify(title) or "untitled"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"
```

`frozenset(existing)` makes repeated membership safe regardless of what was passed and drops the second scan to O(1). Regression test: `unique_slug("Hello", iter(["hello-2", "hello"])) == "hello-3"`.

## Status of the fix

Not applied and not test-run: this session is read-only (`Bash` denied, no edit tool), so both patches above are unverified by execution — they are derived from reading `src/slug.py:1-23`. Apply and run `python -m pytest` per `README.md:2` to confirm.

## Verdict

One defect (`src/slug.py:9-11`, documented transliteration contract violated, can force spurious collisions) and one hazard (`src/slug.py:17,20`, double consumption of `existing` yields a duplicate slug for iterator inputs); both have exact patches above and neither is applied.