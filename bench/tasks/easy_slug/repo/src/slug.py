"""URL slug generation for article titles."""
import re


def slugify(title: str) -> str:
    """Lowercase ASCII slug: words joined by single hyphens, no leading/trailing
    hyphens. Accented latin letters must transliterate to their ASCII base
    (café -> cafe); characters with no ASCII base are dropped."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)  # BUG: strips accents entirely instead of transliterating
    return s.strip("-")


def unique_slug(title: str, existing) -> str:
    """slugify(), then ensure uniqueness against `existing` by appending -2, -3, ..."""
    base = slugify(title) or "untitled"
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"
