from intervals import find_free_slots


def test_free_time_between_meetings():
    assert find_free_slots([(9, 10), (11, 12)], 8, 17) == [(8, 9), (10, 11), (12, 17)]


def test_back_to_back_meetings_leave_no_gap():
    assert find_free_slots([(9, 10), (10, 11)], 9, 12) == [(11, 12)]


def test_overlapping_meetings_block_their_union():
    assert find_free_slots([(9, 11), (10, 12)], 8, 14) == [(8, 9), (12, 14)]


def test_empty_calendar_is_all_free():
    assert find_free_slots([], 8, 17) == [(8, 17)]
