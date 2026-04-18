import pytest

from backend.src.elicitation.priority_table import (
    DEFAULT_PRIORITY,
    DIMENSION_PRIORITY,
    get_priority,
)


def test_exact_match_coffee():
    assert get_priority("coffee") == ["outcome", "population", "dose"]


def test_exact_match_turmeric_form_first():
    assert get_priority("turmeric")[0] == "form"


def test_case_insensitive():
    assert get_priority("COFFEE") == get_priority("coffee")
    assert get_priority("Coffee") == get_priority("coffee")
    assert get_priority("Red Meat") == get_priority("red meat")
    assert get_priority("Vitamin D") == get_priority("vitamin d")


def test_whitespace_trimmed():
    assert get_priority("  turmeric  ") == get_priority("turmeric")


def test_fuzzy_match_plural():
    assert get_priority("coffees") == get_priority("coffee")


def test_fuzzy_match_typo():
    assert get_priority("turmeic") == get_priority("turmeric")


def test_unknown_food_returns_default():
    assert get_priority("zucchini") == DEFAULT_PRIORITY


def test_empty_string_returns_default():
    assert get_priority("") == DEFAULT_PRIORITY


def test_none_returns_default():
    assert get_priority(None) == DEFAULT_PRIORITY


def test_default_priority_shape():
    assert DEFAULT_PRIORITY == ["outcome", "population", "form"]


def test_returned_list_is_independent_copy():
    # Mutating the result must not corrupt the module-level table.
    result = get_priority("coffee")
    result.append("junk")
    assert get_priority("coffee") == ["outcome", "population", "dose"]


@pytest.mark.parametrize("food", list(DIMENSION_PRIORITY.keys()))
def test_every_entry_has_2_to_4_slots(food):
    assert 2 <= len(DIMENSION_PRIORITY[food]) <= 4


@pytest.mark.parametrize("food", list(DIMENSION_PRIORITY.keys()))
def test_every_entry_uses_valid_slots(food):
    valid_slots = {"form", "dose", "frequency", "population", "component", "outcome"}
    for slot in DIMENSION_PRIORITY[food]:
        assert slot in valid_slots


@pytest.mark.parametrize("food", list(DIMENSION_PRIORITY.keys()))
def test_every_entry_has_unique_slots(food):
    slots = DIMENSION_PRIORITY[food]
    assert len(slots) == len(set(slots))


def test_all_ten_demo_foods_present():
    expected = {
        "coffee",
        "turmeric",
        "red meat",
        "eggs",
        "alcohol",
        "vitamin d",
        "intermittent fasting",
        "artificial sweeteners",
        "added sugar",
        "dairy milk",
    }
    assert expected <= set(DIMENSION_PRIORITY.keys())
