from slugger import slugify, unique_slug


def test_basic():
    assert slugify("Hello World") == "hello-world"


def test_accents_are_folded():
    assert slugify("Crème Brûlée") == "creme-brulee"


def test_punctuation_is_dropped():
    assert slugify("Rock & Roll, Baby!") == "rock-roll-baby"


def test_custom_separator():
    assert slugify("a b c", sep="_") == "a_b_c"


def test_numbers_survive():
    assert slugify("Python 3.12 rocks") == "python-312-rocks"


def test_collapses_repeated_separators():
    assert slugify("hello --  world") == "hello-world"


def test_trims_separators_at_both_ends():
    assert slugify("  --Hi there--  ") == "hi-there"


def test_hyphens_follow_custom_separator():
    assert slugify("a-b c", sep="_") == "a_b_c"


def test_max_length_cuts_on_a_clean_boundary():
    assert slugify("hello world again", max_length=6) == "hello"


def test_max_length_exact_fit():
    assert slugify("hello world", max_length=11) == "hello-world"


def test_empty_and_symbols_only():
    assert slugify("") == ""
    assert slugify("!!!") == ""


def test_unique_slug_skips_taken():
    assert unique_slug("Hello World", {"hello-world", "hello-world-2"}) == "hello-world-3"


def test_unique_slug_custom_separator():
    assert unique_slug("Hello World", {"hello_world"}, sep="_") == "hello_world_2"
