from intervals import merge_intervals, total_covered


def test_disjoint_intervals_are_untouched():
    assert merge_intervals([(1, 2), (4, 5)]) == [(1, 2), (4, 5)]


def test_overlapping_intervals_merge():
    assert merge_intervals([(1, 3), (2, 6), (8, 10)]) == [(1, 6), (8, 10)]


def test_touching_intervals_merge():
    assert merge_intervals([(1, 2), (2, 3)]) == [(1, 3)]


def test_contained_interval_is_absorbed():
    assert merge_intervals([(1, 10), (2, 3)]) == [(1, 10)]


def test_unsorted_input():
    assert merge_intervals([(8, 10), (1, 3), (2, 6)]) == [(1, 6), (8, 10)]


def test_empty_and_single():
    assert merge_intervals([]) == []
    assert merge_intervals([(5, 6)]) == [(5, 6)]


def test_input_is_not_mutated():
    data = [(3, 4), (1, 2)]
    merge_intervals(data)
    assert data == [(3, 4), (1, 2)]


def test_negative_numbers():
    assert merge_intervals([(-5, -1), (-3, 2)]) == [(-5, 2)]


def test_total_covered_counts_overlap_once():
    assert total_covered([(0, 5), (3, 8)]) == 8


def test_total_covered_disjoint():
    assert total_covered([(0, 1), (5, 7)]) == 3
