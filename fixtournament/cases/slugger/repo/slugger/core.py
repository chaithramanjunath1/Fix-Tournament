"""Turn arbitrary text into URL-friendly slugs."""
import re
import unicodedata


def slugify(text, sep="-", max_length=None):
    """Return a lowercase, ASCII-folded slug for *text*.

    Runs of whitespace, underscores and hyphens collapse into a single
    separator, and no separator appears at either end of the result.
    If *max_length* is given the slug is cut to that length without
    leaving a dangling separator.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_]+", sep, text)
    if max_length:
        text = text[:max_length]
    return text


def unique_slug(text, taken, sep="-"):
    """Return a slug for *text* that does not collide with anything in *taken*."""
    base = slugify(text, sep=sep)
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}{sep}{n}"
        n += 1
    return candidate
