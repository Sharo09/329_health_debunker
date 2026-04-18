"""Tests for Station 1 schemas (Task 1)."""

import pytest
from pydantic import ValidationError

from backend.src.extraction.schemas import (
    SLOT_NAMES,
    VAGUE_VALUES,
    FlatPartialPICO,
    PartialPICO,
    SlotExtraction,
    compute_ambiguous_slots,
)


# ---------- SlotExtraction ----------

def test_slot_extraction_explicit_valid():
    s = SlotExtraction(value="coffee", confidence="explicit", source_span="coffee")
    assert s.value == "coffee"
    assert s.source_span == "coffee"


def test_slot_extraction_implied_valid_with_and_without_source_span():
    SlotExtraction(value="elderly", confidence="implied", source_span="my grandma")
    SlotExtraction(value="elderly", confidence="implied")  # source_span optional on implied


def test_slot_extraction_absent_valid():
    s = SlotExtraction(confidence="absent")
    assert s.value is None
    assert s.source_span is None


def test_slot_extraction_default_is_absent():
    s = SlotExtraction()
    assert s.confidence == "absent"
    assert s.value is None


def test_explicit_without_source_span_raises():
    with pytest.raises(ValidationError) as exc:
        SlotExtraction(value="coffee", confidence="explicit")
    assert "source_span" in str(exc.value)


def test_explicit_without_value_raises():
    with pytest.raises(ValidationError) as exc:
        SlotExtraction(confidence="explicit", source_span="coffee")
    assert "value" in str(exc.value)


def test_absent_with_non_null_value_raises():
    with pytest.raises(ValidationError) as exc:
        SlotExtraction(value="coffee", confidence="absent")
    assert "absent" in str(exc.value).lower()


def test_invalid_confidence_literal_raises():
    with pytest.raises(ValidationError):
        SlotExtraction(confidence="maybe")  # type: ignore[arg-type]


# ---------- compute_ambiguous_slots ----------

def test_all_slots_absent_are_all_ambiguous():
    pico = PartialPICO(raw_claim="unknown")
    assert set(pico.ambiguous_slots) == set(SLOT_NAMES)


def test_explicit_food_is_not_ambiguous():
    pico = PartialPICO(
        raw_claim="Is coffee bad?",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
    )
    assert "food" not in pico.ambiguous_slots
    # everything else is absent
    for slot in SLOT_NAMES:
        if slot == "food":
            continue
        assert slot in pico.ambiguous_slots


def test_implied_slot_is_not_ambiguous_by_default():
    # Task 1 rule: ambiguous == absent OR vague-value. "implied" with a
    # concrete value is NOT ambiguous here; Station 2 layers priority
    # filtering on top.
    pico = PartialPICO(
        raw_claim="Is this good for my grandma?",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
        population=SlotExtraction(
            value="elderly", confidence="implied", source_span="my grandma"
        ),
    )
    assert "population" not in pico.ambiguous_slots


def test_vague_value_is_ambiguous():
    pico = PartialPICO(
        raw_claim="Is a lot of coffee bad?",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
        dose=SlotExtraction(value="a lot", confidence="explicit", source_span="a lot"),
    )
    assert "dose" in pico.ambiguous_slots


@pytest.mark.parametrize("vague", sorted(VAGUE_VALUES))
def test_every_vague_value_flags_slot(vague):
    pico = PartialPICO(
        raw_claim="x",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
        dose=SlotExtraction(value=vague, confidence="explicit", source_span=vague),
    )
    assert "dose" in pico.ambiguous_slots


def test_vague_value_case_insensitive_and_trimmed():
    pico = PartialPICO(
        raw_claim="x",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
        dose=SlotExtraction(value="  A LOT  ", confidence="explicit", source_span="a lot"),
    )
    assert "dose" in pico.ambiguous_slots


def test_concrete_non_vague_value_is_not_ambiguous():
    pico = PartialPICO(
        raw_claim="x",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
        dose=SlotExtraction(
            value="2-3 cups/day", confidence="explicit", source_span="2-3 cups/day"
        ),
    )
    assert "dose" not in pico.ambiguous_slots


def test_ambiguous_slots_caller_supplied_value_is_overridden():
    # Caller passes a garbage list; the validator recomputes it.
    pico = PartialPICO(
        raw_claim="x",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
        ambiguous_slots=["totally", "wrong", "entries"],
    )
    for bad in ("totally", "wrong", "entries"):
        assert bad not in pico.ambiguous_slots
    assert "food" not in pico.ambiguous_slots
    assert "outcome" in pico.ambiguous_slots


def test_compute_ambiguous_slots_is_the_same_function_used_by_validator():
    pico = PartialPICO(
        raw_claim="x",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
    )
    assert compute_ambiguous_slots(pico) == pico.ambiguous_slots


# ---------- to_flat() ----------

def test_to_flat_drops_slot_extraction_wrappers():
    pico = PartialPICO(
        raw_claim="Is coffee bad for heart disease?",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
        outcome=SlotExtraction(
            value="heart disease", confidence="explicit", source_span="heart disease"
        ),
    )
    flat = pico.to_flat()
    assert isinstance(flat, FlatPartialPICO)
    assert flat.raw_claim == "Is coffee bad for heart disease?"
    assert flat.food == "coffee"
    assert flat.outcome == "heart disease"
    assert flat.form is None
    assert flat.dose is None
    assert flat.frequency is None
    assert flat.population is None
    assert flat.component is None


def test_to_flat_preserves_ambiguous_slots():
    pico = PartialPICO(
        raw_claim="Is coffee bad?",
        food=SlotExtraction(value="coffee", confidence="explicit", source_span="coffee"),
    )
    flat = pico.to_flat()
    assert set(flat.ambiguous_slots) == set(pico.ambiguous_slots)
    # Deep copy: mutating flat's list must not affect the rich PICO.
    flat.ambiguous_slots.append("x")
    assert "x" not in pico.ambiguous_slots


def test_to_flat_on_fully_absent_pico():
    pico = PartialPICO(raw_claim="what?")
    flat = pico.to_flat()
    for field in ("food", "form", "dose", "frequency", "population", "component", "outcome"):
        assert getattr(flat, field) is None
    assert set(flat.ambiguous_slots) == set(SLOT_NAMES)


# ---------- Scope gate / notes ----------

def test_scope_rejection_fields_default_to_food_claim():
    pico = PartialPICO(raw_claim="x")
    assert pico.is_food_claim is True
    assert pico.scope_rejection_reason is None
    assert pico.notes is None


def test_scope_rejection_reason_can_be_set():
    pico = PartialPICO(
        raw_claim="Does aspirin prevent heart attacks?",
        is_food_claim=False,
        scope_rejection_reason="aspirin is a drug, not a food/nutrition claim",
    )
    assert pico.is_food_claim is False
    assert pico.scope_rejection_reason.startswith("aspirin")
