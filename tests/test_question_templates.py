import pytest

from src.elicitation.priority_table import DIMENSION_PRIORITY
from src.elicitation.question_templates import (
    FALLBACK_VALUE,
    GENERIC_TEMPLATES,
    QUESTION_TEMPLATES,
    get_question,
)


VALID_SLOTS = {"form", "dose", "frequency", "population", "component", "outcome"}


# ---- schema integrity ----

def _priority_pairs() -> list[tuple[str, str]]:
    pairs = []
    for food, slots in DIMENSION_PRIORITY.items():
        for slot in slots:
            pairs.append((slot, food))
    return pairs


@pytest.mark.parametrize("key", list(QUESTION_TEMPLATES.keys()))
def test_template_schema_fields(key):
    t = QUESTION_TEMPLATES[key]
    assert isinstance(t["text"], str) and t["text"].strip()
    assert isinstance(t["options"], list)
    assert isinstance(t["option_values"], list)
    assert isinstance(t["allow_other"], bool)


@pytest.mark.parametrize("key", list(QUESTION_TEMPLATES.keys()))
def test_options_and_values_same_length(key):
    t = QUESTION_TEMPLATES[key]
    assert len(t["options"]) == len(t["option_values"])


@pytest.mark.parametrize("key", list(QUESTION_TEMPLATES.keys()))
def test_option_count_in_range(key):
    # Spec says 3-6 options; allow one extra for the "Not sure" fallback.
    t = QUESTION_TEMPLATES[key]
    assert 3 <= len(t["options"]) <= 7


@pytest.mark.parametrize("key", list(QUESTION_TEMPLATES.keys()))
def test_option_values_unique(key):
    values = QUESTION_TEMPLATES[key]["option_values"]
    assert len(values) == len(set(values))


@pytest.mark.parametrize("key", list(QUESTION_TEMPLATES.keys()))
def test_has_fallback_value(key):
    # Every template must expose a way for the user to say "don't know".
    assert FALLBACK_VALUE in QUESTION_TEMPLATES[key]["option_values"]


@pytest.mark.parametrize("key", list(QUESTION_TEMPLATES.keys()))
def test_slot_in_key_is_valid(key):
    slot, _food = key
    assert slot in VALID_SLOTS


# ---- coverage vs. priority table ----

@pytest.mark.parametrize("slot,food", _priority_pairs())
def test_every_priority_pair_has_template(slot, food):
    assert (slot, food) in QUESTION_TEMPLATES, (
        f"Missing template for priority pair ({slot!r}, {food!r})."
    )


# ---- generic templates ----

@pytest.mark.parametrize("slot", sorted(VALID_SLOTS))
def test_generic_template_exists_for_every_slot(slot):
    assert slot in GENERIC_TEMPLATES


@pytest.mark.parametrize("slot", sorted(VALID_SLOTS))
def test_generic_schema(slot):
    t = GENERIC_TEMPLATES[slot]
    assert len(t["options"]) == len(t["option_values"])
    assert FALLBACK_VALUE in t["option_values"]
    assert isinstance(t["allow_other"], bool)


# ---- get_question lookup ----

def test_get_question_exact_pair():
    t = get_question("form", "turmeric")
    assert "turmeric" in t["text"].lower()
    assert "supplement" in t["option_values"]


def test_get_question_case_insensitive_food():
    assert get_question("form", "Turmeric") == get_question("form", "turmeric")
    assert get_question("form", "TURMERIC") == get_question("form", "turmeric")


def test_get_question_whitespace_trimmed():
    assert get_question("form", "  turmeric  ") == get_question("form", "turmeric")


def test_get_question_falls_back_to_generic():
    # (population, zucchini) has no specific template; should return the
    # generic population template.
    result = get_question("population", "zucchini")
    assert result is GENERIC_TEMPLATES["population"]


def test_get_question_generic_when_food_is_none():
    assert get_question("outcome", None) is GENERIC_TEMPLATES["outcome"]


def test_get_question_raises_when_slot_unknown_and_no_generic():
    with pytest.raises(KeyError):
        get_question("not_a_real_slot", "coffee")


def test_get_question_unknown_food_unknown_slot_raises():
    with pytest.raises(KeyError):
        get_question("not_a_real_slot", "zucchini")
