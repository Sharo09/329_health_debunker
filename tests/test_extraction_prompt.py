"""Tests for the extraction prompt (Task 3)."""

import json

import pytest

from src.extraction.prompt import (
    EXTRACTION_SYSTEM_PROMPT,
    _FEW_SHOT_EXAMPLES,
    build_extraction_prompt,
)
from src.extraction.schemas import SLOT_NAMES, PartialPICO


# ---------- system prompt content ----------

def test_system_prompt_mentions_absent_confidence_level():
    assert "absent" in EXTRACTION_SYSTEM_PROMPT.lower()


def test_system_prompt_forbids_fabrication():
    body = EXTRACTION_SYSTEM_PROMPT.lower()
    assert "never fabricate" in body


def test_system_prompt_names_all_seven_slots():
    body = EXTRACTION_SYSTEM_PROMPT.lower()
    for slot in SLOT_NAMES:
        assert slot in body, f"system prompt does not mention slot {slot!r}"


def test_system_prompt_names_all_three_confidence_levels():
    body = EXTRACTION_SYSTEM_PROMPT.lower()
    for level in ("explicit", "implied", "absent"):
        assert level in body


def test_system_prompt_declares_scope_rule():
    body = EXTRACTION_SYSTEM_PROMPT.lower()
    assert "scope" in body
    assert "drug" in body or "aspirin" in body


# ---------- few-shot examples ----------

def test_at_least_six_few_shot_examples():
    assert len(_FEW_SHOT_EXAMPLES) >= 6


def test_few_shot_example_count_within_range():
    # We now have 13 examples (added 3 for the component-inference rule).
    # Keep a sane upper bound to catch prompt bloat.
    assert 6 <= len(_FEW_SHOT_EXAMPLES) <= 20


@pytest.mark.parametrize("idx,example", list(enumerate(_FEW_SHOT_EXAMPLES)))
def test_each_example_round_trips_through_json(idx, example):
    # The dict is already native Python, but check it serializes cleanly.
    encoded = json.dumps(example["pico"])
    decoded = json.loads(encoded)
    assert decoded == example["pico"]


@pytest.mark.parametrize("idx,example", list(enumerate(_FEW_SHOT_EXAMPLES)))
def test_each_example_validates_against_partial_pico(idx, example):
    pico = PartialPICO(**example["pico"])
    assert pico.raw_claim == example["claim"]


def test_fully_specified_example_has_all_slots_non_absent():
    ex = _FEW_SHOT_EXAMPLES[0]
    pico = PartialPICO(**ex["pico"])
    # At least food/dose/frequency/population/outcome should be non-absent.
    assert pico.food.confidence != "absent"
    assert pico.dose.confidence != "absent"
    assert pico.population.confidence != "absent"
    assert pico.outcome.confidence != "absent"


def test_scope_rejection_example_has_is_food_claim_false():
    rejection = next(
        ex for ex in _FEW_SHOT_EXAMPLES if ex["pico"]["is_food_claim"] is False
    )
    pico = PartialPICO(**rejection["pico"])
    assert pico.is_food_claim is False
    assert pico.scope_rejection_reason is not None
    for slot in SLOT_NAMES:
        assert getattr(pico, slot).confidence == "absent"


def test_compound_claim_example_has_notes():
    compound = next(
        ex for ex in _FEW_SHOT_EXAMPLES
        if "compound" in (ex["pico"].get("notes") or "").lower()
    )
    pico = PartialPICO(**compound["pico"])
    assert pico.notes is not None
    assert "compound" in pico.notes.lower()


def test_vague_dose_example_uses_vague_value_verbatim():
    vague = next(
        ex for ex in _FEW_SHOT_EXAMPLES
        if ex["pico"]["dose"]["value"] == "a lot"
    )
    pico = PartialPICO(**vague["pico"])
    # The validator flags "a lot" as ambiguous.
    assert "dose" in pico.ambiguous_slots


def test_implied_population_example_grandma_to_elderly():
    grandma = next(
        ex for ex in _FEW_SHOT_EXAMPLES
        if "grandma" in ex["claim"].lower()
    )
    assert grandma["pico"]["population"]["value"] == "elderly"
    assert grandma["pico"]["population"]["confidence"] == "implied"


def test_component_example_names_a_compound():
    component_ex = next(
        ex for ex in _FEW_SHOT_EXAMPLES
        if ex["pico"]["component"]["value"] is not None
    )
    assert component_ex["pico"]["component"]["value"] in {"caffeine", "curcumin"}


def test_supplement_example_has_form_supplement():
    sup = next(
        ex for ex in _FEW_SHOT_EXAMPLES
        if ex["pico"]["form"]["value"] == "supplement"
    )
    assert sup["pico"]["form"]["confidence"] == "explicit"


def test_every_explicit_slot_has_source_span():
    # Schema validator enforces this, but verify our examples exercise it.
    for ex in _FEW_SHOT_EXAMPLES:
        for slot in SLOT_NAMES:
            slot_data = ex["pico"][slot]
            if slot_data["confidence"] == "explicit":
                assert slot_data["source_span"] is not None, (
                    f"example {ex['claim']!r}: explicit slot {slot} missing source_span"
                )


# ---------- build_extraction_prompt ----------

def test_build_extraction_prompt_returns_system_plus_user():
    msgs = build_extraction_prompt("Is coffee bad?")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == EXTRACTION_SYSTEM_PROMPT
    assert msgs[1]["role"] == "user"
    assert "Is coffee bad?" in msgs[1]["content"]


def test_build_extraction_prompt_includes_raw_claim_verbatim():
    claim = "Does 2-3 cups of coffee per day during pregnancy cause miscarriage?"
    msgs = build_extraction_prompt(claim)
    assert claim in msgs[1]["content"]
