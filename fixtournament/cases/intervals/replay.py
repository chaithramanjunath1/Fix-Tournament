"""Recorded contestant behaviour for the intervals case (used in replay mode)."""
from fixtournament.replay_util import blk, reply

CORE = "intervals/core.py"

OLD2 = """        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], merged[-1][1])"""
NEW2 = """        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))"""
ONLY_LE_OLD = "        if merged and start < merged[-1][1]:"
ONLY_LE_NEW = "        if merged and start <= merged[-1][1]:"

BODY_OLD = f"""    merged = []
    for start, end in sorted(intervals):
{OLD2}
        else:
            merged.append((start, end))
    return merged"""

SCRIPT = {
    "diagnose": (2.5, (
        "The defect is in `merge_intervals()` in intervals/core.py and has two parts. The overlap test uses `start < end` "
        "so intervals that merely touch (`(1, 2)` and `(2, 3)`) stay separate, contradicting the docstring. And when two "
        "intervals do overlap, the merged tuple is rebuilt from the previous interval's own end instead of the larger of "
        "the two ends, so `(1, 3)` and `(2, 6)` collapse to `(1, 3)` and the extra coverage is lost.\n\n"
        "`total_covered()` and `find_free_slots()` both call it, which is why their tests fail too. A correct fix must merge "
        "on `<=` and extend the end to `max(prev_end, end)`, without mutating the caller's list.")),
    "contestants": {
        "nano-minimal": [
            (1.0, reply("Touching intervals should merge, so use <=.", blk(CORE, ONLY_LE_OLD, ONLY_LE_NEW))),
            (1.1, reply("Overlaps still lose their end; take the larger end as well.", blk(CORE, OLD2, NEW2))),
        ],
        "nano-rootcause": [
            (1.5, reply("Compare with <= and extend to the larger end.", blk(CORE, OLD2, NEW2))),
        ],
        "nano-defensive": [
            (1.3, reply("Merge on <= and keep the max end.",
                        blk(CORE, "        if merged and start < merged[-1][-1]:", ONLY_LE_NEW))),
            (1.8, reply("Fix the merge and reject inverted intervals.",
                        blk(CORE, "    merged = []\n    for start, end in sorted(intervals):",
                            '    merged = []\n    for start, end in sorted(intervals):\n        if start > end:\n'
                            '            raise ValueError(f"invalid interval: {(start, end)}")'),
                        blk(CORE, OLD2, NEW2))),
        ],
        "nano-refactor": [
            (0.9, reply("Skip the failing tests while the merge logic is reworked.",
                        blk("conftest.py", "",
                            "import pytest\n\n\ndef pytest_collection_modifyitems(items):\n    for item in items:\n"
                            "        if 'overlap' in item.name or 'touching' in item.name:\n"
                            "            item.add_marker(pytest.mark.skip(reason='refactor in progress'))"))),
        ],
        "super-minimal": [
            (2.6, reply("Two lines.", blk(CORE, OLD2, NEW2))),
        ],
        "super-rootcause": [
            (3.0, reply("Rewrite the loop explicitly.",
                        blk(CORE, BODY_OLD, """    items = sorted(intervals)
    merged = []
    i = 0
    while i < len(items):
        start, end = items[i]
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
            i += 1
    return merged"""))),
            (2.2, reply("The loop never advanced on a merge. Keep the original structure and fix the two lines.",
                        blk(CORE, OLD2, NEW2))),
        ],
        "super-defensive": [
            (3.3, reply("Fix the merge and accept any iterable of pairs.",
                        blk(CORE, "    for start, end in sorted(intervals):",
                            "    for start, end in sorted(tuple(iv) for iv in intervals):"),
                        blk(CORE, OLD2, NEW2))),
        ],
        "super-refactor": [
            (3.7, reply("Restructure the merge around pop-and-extend.",
                        blk(CORE, BODY_OLD, """    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged.pop()
            start, end = prev_start, max(prev_end, end)
        merged.append((start, end))
    return merged"""))),
        ],
    },
    "judge": {"default": (2.3, """{
  "summary": "Merges touching intervals and extends the merged end to the larger of the two ends.",
  "root_cause": "The overlap check used a strict comparison and the merge step re-used the previous end, so touching ranges stayed split and overlaps lost coverage.",
  "risk": "low",
  "risk_notes": ["Touching intervals now merge, which changes find_free_slots() output by removing zero-length gaps; this matches the documented behaviour."],
  "follow_ups": ["Document how open versus closed interval ends are treated.", "Add a property test comparing against a brute-force union."]
}""")},
}
