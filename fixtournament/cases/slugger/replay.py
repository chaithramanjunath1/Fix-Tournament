"""Recorded contestant behaviour for the slugger case (used in replay mode).

Each contestant's list is its reply per turn: (simulated latency in seconds, text).
The behaviours are deliberately varied: clean fixes, a partial fix that needs a
second turn, a hallucinated SEARCH block, a test-tampering attempt, a regression
that hard-codes the separator, a missing dependency, and one that runs out of turns.
"""
from fixtournament.replay_util import blk, reply

CORE = "slugger/core.py"
TEST = "tests/test_core.py"

COLLAPSE_OLD = '    text = re.sub(r"[\\s_]+", sep, text)'
COLLAPSE_NEW = '    text = re.sub(r"[\\s_-]+", sep, text).strip(sep)'
TRUNC_OLD = "        text = text[:max_length]"
TRUNC_NEW = "        text = text[:max_length].strip(sep)"

FULL_FIX = [blk(CORE, COLLAPSE_OLD, COLLAPSE_NEW), blk(CORE, TRUNC_OLD, TRUNC_NEW)]

TAIL_OLD = f"""{COLLAPSE_OLD}
    if max_length:
        text = text[:max_length]
    return text"""
TAIL_NEW = """    text = re.sub(r"[\\s_-]+", sep, text)
    if max_length:
        text = text[:max_length]
    return text.strip(sep)"""

FOLD_OLD = """    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")"""

WHOLE_OLD = f"""{FOLD_OLD}
    text = re.sub(r"[^\\w\\s-]", "", text).strip().lower()
{COLLAPSE_OLD}
    if max_length:
        text = text[:max_length]
    return text"""

def whole(trunc_line: str) -> str:
    return f"""    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^\\w\\s-]", "", folded).lower()
    slug = re.sub(r"[\\s_-]+", sep, cleaned).strip(sep)
    if max_length:
        {trunc_line}
    return slug"""

SCRIPT = {
    "diagnose": (2.4, (
        "The bug is in `slugify()` in slugger/core.py. Separators are only produced from whitespace and underscores "
        "(`[\\s_]+`), so hyphens already in the input survive untouched: that is why runs like `--` are not collapsed, why "
        "leading and trailing hyphens remain, and why a custom separator never replaces input hyphens. Separately, "
        "`max_length` truncates after the slug is built, which can cut right after a separator and leave it dangling.\n\n"
        "A correct fix must treat whitespace, underscores and hyphens as one separator class, strip the separator from "
        "both ends, and strip again after truncation. It must keep honouring a custom `sep`; `unique_slug()` depends on that.")),
    "contestants": {
        "nano-minimal": [
            (1.1, reply("Treat hyphens as separators and trim the ends.", blk(CORE, COLLAPSE_OLD, COLLAPSE_NEW))),
            (1.0, reply("The truncation can still leave a dangling separator; trim there too.", *FULL_FIX)),
        ],
        "nano-rootcause": [
            (1.4, reply("Hyphens were never treated as separators, and truncation is not trimmed.", *FULL_FIX)),
        ],
        "nano-defensive": [
            (1.2, reply("Collapse separators.", blk(CORE, COLLAPSE_OLD.replace('"', "'"), COLLAPSE_NEW))),
            (1.7, reply("Fix the separators and reject non-string input.",
                        blk(CORE, '    text = unicodedata.normalize("NFKD", text)',
                            '    if not isinstance(text, str):\n        raise TypeError("slugify() expects a string")\n'
                            '    text = unicodedata.normalize("NFKD", text)'),
                        *FULL_FIX)),
        ],
        "nano-refactor": [
            (0.9, reply("The truncation expectation looks wrong, align the test with current behaviour.",
                        blk(TEST, '    assert slugify("hello world again", max_length=6) == "hello"',
                            '    assert slugify("hello world again", max_length=6) == "hello-"'))),
        ],
        "super-minimal": [
            (2.7, reply("Two lines: one separator class, and strip once at the end.", blk(CORE, TAIL_OLD, TAIL_NEW))),
        ],
        "super-rootcause": [
            (3.0, reply("Collapse every separator run to a single hyphen and trim.",
                        blk(CORE, COLLAPSE_OLD, '    text = re.sub(r"[\\s_-]+", "-", text).strip("-")'),
                        blk(CORE, TRUNC_OLD, '        text = text[:max_length].strip("-")'))),
            (2.4, reply("That hard-coded the hyphen and ignored `sep`. Name the separator pattern and use `sep`.",
                        blk(CORE, "import unicodedata",
                            'import unicodedata\n\n_SEPARATOR_RUN = re.compile(r"[\\s_-]+")'),
                        blk(CORE, COLLAPSE_OLD, "    text = _SEPARATOR_RUN.sub(sep, text).strip(sep)"),
                        blk(CORE, TRUNC_OLD, TRUNC_NEW))),
        ],
        "super-defensive": [
            (3.2, reply("Split on any separator run and rejoin, then trim after truncation.",
                        blk(CORE, COLLAPSE_OLD,
                            '    words = re.split(r"[\\s_-]+", text)\n    text = sep.join(w for w in words if w)'),
                        blk(CORE, TRUNC_OLD, "        text = text[:max_length].rstrip(sep)"))),
        ],
        "super-refactor": [
            (2.8, reply("Use a dedicated transliteration library and rebuild the pipeline.",
                        blk(CORE, "import unicodedata", "import unicodedata\nfrom unidecode import unidecode"),
                        blk(CORE, FOLD_OLD, "    text = unidecode(text)"),
                        blk(CORE, COLLAPSE_OLD, COLLAPSE_NEW))),
            (2.6, reply("Drop the dependency; rebuild with the standard library.",
                        blk(CORE, WHOLE_OLD, whole("slug = slug[:max_length]")))),
            (2.2, reply("Cut one character early so a trailing separator can never be kept.",
                        blk(CORE, WHOLE_OLD, whole("slug = slug[: max_length - 1]")))),
        ],
    },
    "judge": {"default": (2.3, """{
  "summary": "Treats hyphens, underscores and whitespace as one separator class and trims separators after truncation.",
  "root_cause": "The separator regex only matched whitespace and underscores, so hyphens in the input survived and leading, trailing and doubled separators leaked through.",
  "risk": "low",
  "risk_notes": ["Behaviour change: input hyphens now follow a custom `sep`; callers relying on literal hyphens with sep='_' will see underscores.", "strip(sep) treats a multi-character sep as a character set; fine for single-character separators."],
  "follow_ups": ["Add a property test: slugify output never starts or ends with sep.", "Decide whether multi-character separators are supported."]
}""")},
}
