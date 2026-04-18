"""Tests for the food normalizer (Task 2)."""

import pytest

from src.extraction.food_normalizer import KNOWN_FOODS, normalize_food


# ---------- exact alias matches ----------

def _all_alias_canonical_pairs():
    return [(alias, canonical) for canonical, aliases in KNOWN_FOODS.items() for alias in aliases]


@pytest.mark.parametrize("alias,canonical", _all_alias_canonical_pairs())
def test_every_alias_resolves_to_its_canonical(alias, canonical):
    name, known = normalize_food(alias)
    assert name == canonical
    assert known is True


# ---------- case / whitespace ----------

def test_case_insensitive():
    assert normalize_food("COFFEE") == ("coffee", True)
    assert normalize_food("Coffee") == ("coffee", True)
    assert normalize_food("Turmeric") == ("turmeric", True)


def test_whitespace_stripped():
    assert normalize_food("  coffee  ") == ("coffee", True)
    assert normalize_food("\tred meat\n") == ("red meat", True)


def test_vitamin_d_canonical_preserves_uppercase_d():
    # Canonical form is "vitamin D" (capital D) even though aliases are lowercase.
    name, known = normalize_food("vit d")
    assert name == "vitamin D"
    assert known is True


# ---------- fuzzy matches ----------

def test_fuzzy_match_cofee_typo():
    assert normalize_food("cofee") == ("coffee", True)


def test_fuzzy_match_tumeric_typo():
    assert normalize_food("tumeric") == ("turmeric", True)


def test_fuzzy_match_alcohal():
    assert normalize_food("alcohal") == ("alcohol", True)


# ---------- substring / phrase matches ----------

def test_cup_of_joe_as_alias():
    assert normalize_food("cup of joe") == ("coffee", True)


def test_substring_match_longer_phrase():
    # "a cup of joe" contains "cup of joe" alias
    name, known = normalize_food("a cup of joe")
    assert known is True
    assert name == "coffee"


def test_multiword_food_not_confused_with_single_word():
    # "red meat" is a KNOWN_FOODS key with its own alias list; it must
    # resolve to "red meat" even though "meat" could conceivably match
    # "processed meat" via substring.
    assert normalize_food("red meat") == ("red meat", True)


def test_processed_meat_wins_over_red_meat_for_bacon():
    assert normalize_food("bacon") == ("processed meat", True)


# ---------- unknown foods ----------

def test_unknown_food_returns_lowercase_and_false():
    name, known = normalize_food("zucchini")
    assert name == "zucchini"
    assert known is False


def test_unknown_food_lowercased():
    name, known = normalize_food("Zucchini")
    assert name == "zucchini"
    assert known is False


def test_empty_string_returns_empty_and_false():
    assert normalize_food("") == ("", False)


def test_whitespace_only_returns_empty_and_false():
    assert normalize_food("   ") == ("", False)


# ---------- false-positive guards ----------

def test_short_alias_not_substring_matched_in_unrelated_word():
    # "if" is an alias for intermittent fasting; it must not match
    # foods where "if" appears as a substring of a larger word.
    name, known = normalize_food("gift basket")
    assert known is False
    assert name == "gift basket"


def test_egg_not_substring_matched_in_leggings():
    name, known = normalize_food("leggings")
    assert known is False


def test_raw_exact_alias_if_still_works():
    # Short aliases still resolve via the exact-match path.
    assert normalize_food("if") == ("intermittent fasting", True)


def test_raw_alias_egg_resolves():
    assert normalize_food("egg") == ("eggs", True)
    assert normalize_food("eggs") == ("eggs", True)


# ---------- specific demo examples ----------

def test_dairy_milk_via_milk_alias():
    assert normalize_food("milk") == ("dairy milk", True)


def test_added_sugar_via_sucrose():
    assert normalize_food("sucrose") == ("added sugar", True)


def test_artificial_sweeteners_via_aspartame():
    assert normalize_food("aspartame") == ("artificial sweeteners", True)


def test_intermittent_fasting_via_16_8():
    assert normalize_food("16:8") == ("intermittent fasting", True)
