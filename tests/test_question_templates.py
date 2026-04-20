import pytest

from src.elicitation.priority_table import DIMENSION_PRIORITY, DIMENSION_ROLE
from src.elicitation.question_templates import (
    FALLBACK_VALUE,
    GENERIC_TEMPLATES,
    QUESTION_TEMPLATES,
    STRATIFIER_HINT,
    get_question,
    render_question_text,
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
    # generic population template (copied, with role injected).
    result = get_question("population", "zucchini")
    base = GENERIC_TEMPLATES["population"]
    assert result["option_values"] == base["option_values"]
    assert result["options"] == base["options"]


def test_get_question_generic_when_food_is_none():
    result = get_question("outcome", None)
    base = GENERIC_TEMPLATES["outcome"]
    assert result["option_values"] == base["option_values"]
    assert result["options"] == base["options"]


def test_get_question_raises_when_slot_unknown_and_no_generic():
    with pytest.raises(KeyError):
        get_question("not_a_real_slot", "coffee")


def test_get_question_unknown_food_unknown_slot_raises():
    with pytest.raises(KeyError):
        get_question("not_a_real_slot", "zucchini")


# ---------- Patch B Task 2 — role + stratifier hint ----------


def _all_slots_used() -> set[str]:
    used = {slot for slot, _ in QUESTION_TEMPLATES.keys()}
    used.update(GENERIC_TEMPLATES.keys())
    return used


@pytest.mark.parametrize("slot", sorted(_all_slots_used()))
def test_get_question_has_role_field(slot):
    """Every template returned by get_question carries a role."""
    t = get_question(slot, None)
    assert "role" in t
    assert t["role"] in ("pre_retrieval", "stratifier")
    assert t["role"] == DIMENSION_ROLE[slot]


@pytest.mark.parametrize(
    "slot,food",
    [(slot, food) for (slot, food) in QUESTION_TEMPLATES.keys()],
)
def test_food_specific_template_role_matches_slot(slot, food):
    t = get_question(slot, food)
    assert t["role"] == DIMENSION_ROLE[slot]


@pytest.mark.parametrize(
    "slot,food",
    [(slot, food) for (slot, food) in QUESTION_TEMPLATES.keys()
     if DIMENSION_ROLE.get(slot) == "stratifier"],
)
def test_stratifier_templates_have_hint_in_text(slot, food):
    """Every stratifier template's rendered text ends with the hint."""
    t = get_question(slot, food)
    assert t["text"].endswith(STRATIFIER_HINT), (
        f"stratifier template ({slot!r}, {food!r}) didn't get the hint "
        f"suffix. Got: {t['text']!r}"
    )


@pytest.mark.parametrize(
    "slot,food",
    [(slot, food) for (slot, food) in QUESTION_TEMPLATES.keys()
     if DIMENSION_ROLE.get(slot) == "pre_retrieval"],
)
def test_pre_retrieval_templates_are_unchanged(slot, food):
    """Pre-retrieval templates' rendered text matches the literal — no hint."""
    t = get_question(slot, food)
    base = QUESTION_TEMPLATES[(slot, food)]
    assert t["text"] == base["text"]
    assert STRATIFIER_HINT not in t["text"]


@pytest.mark.parametrize("slot", sorted(GENERIC_TEMPLATES.keys()))
def test_generic_template_hint_matches_role(slot):
    t = get_question(slot, None)
    if DIMENSION_ROLE[slot] == "stratifier":
        assert t["text"].endswith(STRATIFIER_HINT)
    else:
        assert t["text"] == GENERIC_TEMPLATES[slot]["text"]
        assert STRATIFIER_HINT not in t["text"]


def test_render_question_text_standalone():
    """render_question_text appends the hint only for stratifier templates."""
    stratifier = {"text": "Q?", "role": "stratifier"}  # type: ignore[typeddict-item]
    pre = {"text": "Q?", "role": "pre_retrieval"}  # type: ignore[typeddict-item]
    assert render_question_text(stratifier).endswith(STRATIFIER_HINT)  # type: ignore[arg-type]
    assert render_question_text(pre) == "Q?"  # type: ignore[arg-type]


def test_get_question_does_not_mutate_source():
    """Calling get_question shouldn't append hints to the module-level dicts."""
    before = QUESTION_TEMPLATES[("dose", "coffee")]["text"]
    _ = get_question("dose", "coffee")
    _ = get_question("dose", "coffee")
    after = QUESTION_TEMPLATES[("dose", "coffee")]["text"]
    assert after == before
    assert STRATIFIER_HINT not in after
