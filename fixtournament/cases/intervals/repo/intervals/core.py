"""Interval arithmetic helpers."""


def merge_intervals(intervals):
    """Merge overlapping or touching ``(start, end)`` pairs.

    The input is not modified. Intervals that share an endpoint, such as
    ``(1, 2)`` and ``(2, 3)``, are merged. The result is sorted by start.
    """
    merged = []
    for start, end in sorted(intervals):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], merged[-1][1])
        else:
            merged.append((start, end))
    return merged


def total_covered(intervals):
    """Total length covered by the union of *intervals*."""
    return sum(end - start for start, end in merge_intervals(intervals))
