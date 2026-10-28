"""Calendar helpers built on interval merging."""
from .core import merge_intervals


def find_free_slots(busy, day_start, day_end):
    """Return the gaps between busy intervals inside [day_start, day_end]."""
    free = []
    cursor = day_start
    for start, end in merge_intervals(busy):
        if start > cursor:
            free.append((cursor, min(start, day_end)))
        cursor = max(cursor, end)
        if cursor >= day_end:
            break
    if cursor < day_end:
        free.append((cursor, day_end))
    return free
