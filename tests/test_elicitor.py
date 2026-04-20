"""Tests for ElicitationAgent (Task 5)."""

import json

import pytest

from src.elicitation.elicitor import ElicitationAgent
from src.elicitation.errors import (
    InsufficientElicitationError,
    UnscopableClaimError,
)
from src.elicitation.priority_table import DEFAULT_PRIORITY
from src.elicitation.question_templates import get_question
from src.schemas import PartialPICO
from tests.fixtures import MockUIAdapter


def _agent(adapter: MockUIAdapter, tmp_path) -> ElicitationAgent:
    return ElicitationAgent(adapter, log_file=str(tmp_path / "elicit.jsonl"))


def _text_for(slot: str, food: str | None) -> str:
    return get_question(slot, food)["text"]


# ---------- 1. Happy path ----------

def test_turmeric_all_ambiguous_asks_form_outcome_population_in_order(tmp_path):
    # turmeric priority: [form, outcome, population]
    adapter = MockUIAdapter([
        ("As a curcumin supplement (standardized extract pills)", "supplement"),
        ("Inflammation (general)", "inflammation"),
        ("Healthy adults", "healthy adults"),
    ])
    partial = PartialPICO(
        raw_claim="Is turmeric good?",
        food="turmeric",
        ambiguous_slots=["form", "outcome", "population", "dose", "frequency"],
    )
    locked = _agent(adapter, tmp_path).elicit(partial)

    assert adapter.asked_slots_texts == [
        _text_for("form", "turmeric"),
        _text_for("outcome", "turmeric"),
        _text_for("population", "turmeric"),
    ]
    assert locked.form == "supplement"
    assert locked.outcome == "inflammation"
    assert locked.population == "healthy adults"
    assert locked.locked is True
    assert len(locked.conversation) == 3
    assert locked.fallbacks_used == []


# ---------- 2. Partial input ----------

def test_outcome_already_specified_is_not_re_asked(tmp_path):
    # turmeric priority: [form, outcome, population] -> skip outcome, ask form+population.
    adapter = MockUIAdapter([
        ("As a curcumin supplement (standardized extract pills)", "supplement"),
        ("Healthy adults", "healthy adults"),
    ])
    partial = PartialPICO(
        raw_claim="Is turmeric good for inflammation?",
        food="turmeric",
        outcome="inflammation",
        ambiguous_slots=["form", "dose", "population", "frequency"],
    )
    locked = _agent(adapter, tmp_path).elicit(partial)

    asked = adapter.asked_slots_texts
    assert len(asked) == 2
    assert _text_for("outcome", "turmeric") not in asked
    assert asked == [_text_for("form", "turmeric"), _text_for("population", "turmeric")]
    assert locked.outcome == "inflammation"


def test_slot_not_in_ambiguous_is_skipped_even_when_none(tmp_path):
    # form is None but NOT in ambiguous_slots -> skip; go to outcome+population.
    adapter = MockUIAdapter([
        ("Inflammation (general)", "inflammation"),
        ("Healthy adults", "healthy adults"),
    ])
    partial = PartialPICO(
        raw_claim="Is turmeric good?",
        food="turmeric",
        ambiguous_slots=["outcome", "population"],
    )
    _agent(adapter, tmp_path).elicit(partial)
    assert _text_for("form", "turmeric") not in adapter.asked_slots_texts


# ---------- 3. Max questions cap ----------

def test_at_most_three_questions_when_all_slots_ambiguous(tmp_path):
    adapter = MockUIAdapter([
        ("Heart disease or blood pressure", "cardiovascular disease"),
        ("Healthy adults", "healthy adults"),
        ("1-2 cups", "moderate"),
    ])
    partial = PartialPICO(
        raw_claim="Is coffee bad for you?",
        food="coffee",
        ambiguous_slots=["outcome", "population", "dose", "form", "frequency", "component"],
    )
    locked = _agent(adapter, tmp_path).elicit(partial)
    assert len(adapter.asked_questions) == 3
    assert locked.outcome == "cardiovascular disease"
    assert locked.population == "healthy adults"
    assert locked.dose == "moderate"


# ---------- 4. "Not sure" answers ----------

def test_not_sure_records_fallback_and_does_not_re_ask(tmp_path):
    adapter = MockUIAdapter([
        ("Not sure", "unknown"),   # form
        ("Not sure", "unknown"),   # population
    ])
    partial = PartialPICO(
        raw_claim="Is turmeric good for inflammation?",
        food="turmeric",
        outcome="inflammation",
        ambiguous_slots=["form", "population"],
    )
    locked = _agent(adapter, tmp_path).elicit(partial)

    assert "form" in locked.fallbacks_used
    assert "population" in locked.fallbacks_used
    assert locked.form == "unknown"
    assert locked.population == "unknown"
    assert len(adapter.asked_questions) == 2  # did not re-ask


def test_not_sure_only_for_some_slots(tmp_path):
    adapter = MockUIAdapter([
        ("As a curcumin supplement (standardized extract pills)", "supplement"),
        ("Not sure", "unknown"),
    ])
    partial = PartialPICO(
        raw_claim="Is turmeric good?",
        food="turmeric",
        outcome="inflammation",
        ambiguous_slots=["form", "population"],
    )
    locked = _agent(adapter, tmp_path).elicit(partial)

    assert locked.form == "supplement"
    assert locked.population == "unknown"
    assert locked.fallbacks_used == ["population"]


# ---------- 5. No food ----------

def test_no_food_raises_unscopable_claim_error(tmp_path):
    adapter = MockUIAdapter([])
    partial = PartialPICO(
        raw_claim="Is this healthy?",
        food=None,
        ambiguous_slots=["outcome", "population"],
    )
    with pytest.raises(UnscopableClaimError):
        _agent(adapter, tmp_path).elicit(partial)


def test_empty_food_string_raises_unscopable_claim_error(tmp_path):
    adapter = MockUIAdapter([])
    partial = PartialPICO(
        raw_claim="Tell me about this food.",
        food="   ",
        ambiguous_slots=[],
    )
    with pytest.raises(UnscopableClaimError):
        _agent(adapter, tmp_path).elicit(partial)


# ---------- 6. Unknown food -> default priority ----------

def test_unknown_food_uses_default_priority(tmp_path):
    # DEFAULT_PRIORITY = ["outcome", "population", "form"]
    adapter = MockUIAdapter([
        ("Heart disease", "cardiovascular disease"),
        ("Healthy adults", "healthy adults"),
        ("As ordinary food", "dietary"),
    ])
    partial = PartialPICO(
        raw_claim="Is zucchini good?",
        food="zucchini",
        ambiguous_slots=["outcome", "population", "form", "dose"],
    )
    locked = _agent(adapter, tmp_path).elicit(partial)

    # Default priority first three were asked, in order.
    assert len(adapter.asked_questions) == 3
    assert DEFAULT_PRIORITY == ["outcome", "population", "form"]
    assert locked.outcome == "cardiovascular disease"
    assert locked.population == "healthy adults"
    assert locked.form == "dietary"


# ---------- 7. Required slots fallback ----------

def test_population_defaults_when_never_asked(tmp_path):
    # Only outcome is ambiguous; population is never asked and stays None.
    adapter = MockUIAdapter([
        ("Inflammation (general)", "inflammation"),
    ])
    partial = PartialPICO(
        raw_claim="Is turmeric good?",
        food="turmeric",
        ambiguous_slots=["outcome"],
    )
    locked = _agent(adapter, tmp_path).elicit(partial)

    assert locked.population == "healthy adults"
    assert "population" in locked.fallbacks_used


def test_outcome_missing_raises_insufficient_elicitation_error(tmp_path):
    adapter = MockUIAdapter([])
    partial = PartialPICO(
        raw_claim="Is turmeric good?",
        food="turmeric",
        ambiguous_slots=[],
    )
    with pytest.raises(InsufficientElicitationError):
        _agent(adapter, tmp_path).elicit(partial)


def test_outcome_unknown_from_fallback_does_not_raise(tmp_path):
    # If user was asked outcome and said "Not sure", outcome="unknown" is
    # allowed through — downstream can degrade to a broad search.
    adapter = MockUIAdapter([
        ("Not sure", "unknown"),
    ])
    partial = PartialPICO(
        raw_claim="Is coffee bad?",
        food="coffee",
        population="healthy adults",
        ambiguous_slots=["outcome"],
    )
    locked = _agent(adapter, tmp_path).elicit(partial)
    assert locked.outcome == "unknown"
    assert "outcome" in locked.fallbacks_used


# ---------- 8. Logging ----------

def test_jsonl_log_written_with_expected_fields(tmp_path):
    log_path = tmp_path / "elicit.jsonl"
    adapter = MockUIAdapter([
        ("As a curcumin supplement (standardized extract pills)", "supplement"),
        ("Healthy adults", "healthy adults"),
    ])
    partial = PartialPICO(
        raw_claim="Is turmeric good for inflammation?",
        food="turmeric",
        outcome="inflammation",
        ambiguous_slots=["form", "population"],
    )
    agent = ElicitationAgent(adapter, log_file=str(log_path))
    locked = agent.elicit(partial)

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])

    for field in (
        "timestamp",
        "raw_claim",
        "input_partial_pico",
        "slots_asked",
        "conversation",
        "locked_pico",
        "fallbacks_used",
    ):
        assert field in rec, f"missing log field: {field}"

    assert rec["raw_claim"] == "Is turmeric good for inflammation?"
    assert rec["slots_asked"] == ["form", "population"]
    assert len(rec["conversation"]) == 2
    assert rec["locked_pico"]["form"] == "supplement"
    assert rec["locked_pico"]["outcome"] == "inflammation"
    assert rec["locked_pico"]["population"] == "healthy adults"
    assert rec["locked_pico"]["locked"] is True
    # Input PICO snapshot preserves the original (pre-locking) form=None.
    assert rec["input_partial_pico"]["form"] is None


def test_multiple_elicitations_append_to_log(tmp_path):
    log_path = tmp_path / "elicit.jsonl"
    partial = PartialPICO(
        raw_claim="x",
        food="coffee",
        population="healthy adults",
        outcome="cardiovascular disease",
        ambiguous_slots=[],
    )
    for _ in range(3):
        ElicitationAgent(MockUIAdapter([]), log_file=str(log_path)).elicit(partial)
    assert len(log_path.read_text().strip().splitlines()) == 3


# ---------- Extra coverage: compound, Other, select_slots_to_ask ----------

def test_compound_food_picks_first_and_logs_warning(tmp_path):
    adapter = MockUIAdapter([
        ("Heart disease or blood pressure", "cardiovascular disease"),
        ("Healthy adults", "healthy adults"),
        ("1-2 cups", "moderate"),
    ])
    partial = PartialPICO(
        raw_claim="Is coffee and tea bad?",
        food="coffee and tea",
        ambiguous_slots=["outcome", "population", "dose"],
    )
    log_path = tmp_path / "elicit.jsonl"
    locked = ElicitationAgent(adapter, log_file=str(log_path)).elicit(partial)

    assert locked.food == "coffee"  # first chunk
    rec = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert "compound_warning" in rec


def test_other_free_text_stored_and_logged(tmp_path):
    adapter = MockUIAdapter([
        ("My specific rare outcome", "My specific rare outcome"),
    ])
    partial = PartialPICO(
        raw_claim="weird claim",
        food="coffee",
        population="healthy adults",
        ambiguous_slots=["outcome"],
    )
    log_path = tmp_path / "elicit.jsonl"
    locked = ElicitationAgent(adapter, log_file=str(log_path)).elicit(partial)

    assert locked.outcome == "My specific rare outcome"
    rec = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert rec.get("other_slots") == ["outcome"]


def test_select_slots_to_ask_respects_priority_order(tmp_path):
    agent = ElicitationAgent(MockUIAdapter([]), log_file=str(tmp_path / "x.jsonl"))
    partial = PartialPICO(
        raw_claim="x",
        food="coffee",  # priority: outcome, population, dose
        ambiguous_slots=["dose", "population", "outcome"],  # intentionally reversed
    )
    assert agent.select_slots_to_ask(partial) == ["outcome", "population", "dose"]
