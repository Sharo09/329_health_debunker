"""Shared test fixtures."""

import json
from dataclasses import dataclass, field
from typing import Optional

from src.elicitation.ui_adapter import UIAdapter


class MockUIAdapter(UIAdapter):
    """Returns pre-scripted answers in order.

    Each answer is a `(display_label, internal_value)` tuple — the same
    shape `UIAdapter.ask` returns. Records the question dicts it was
    asked so tests can inspect the interaction.
    """

    def __init__(self, answers: list[tuple[str, str]]):
        self.answers = list(answers)
        self.asked_questions: list[dict] = []

    def ask(self, question: dict) -> tuple[str, str]:
        self.asked_questions.append(dict(question))
        if not self.answers:
            raise AssertionError(
                "MockUIAdapter: ran out of scripted answers "
                f"(already asked {len(self.asked_questions)} question(s))."
            )
        return self.answers.pop(0)

    @property
    def asked_slots_texts(self) -> list[str]:
        return [q["text"] for q in self.asked_questions]


# --------- extraction fixtures ---------

def mock_llm_provider(response_dict: dict):
    """Build an LLM provider callable that returns a fixed JSON response.

    Compatible with ``LLMClient(provider=...)``. Used by the extractor
    tests to avoid real API calls.
    """

    def provider(messages, response_schema, model, temperature):
        return json.dumps(response_dict)

    return provider


def _absent_slot() -> dict:
    return {"value": None, "confidence": "absent", "source_span": None}


def _explicit(value: str, span: str) -> dict:
    return {"value": value, "confidence": "explicit", "source_span": span}


def _implied(value: str, span: Optional[str] = None) -> dict:
    return {"value": value, "confidence": "implied", "source_span": span}


def _make_pico_dict(
    raw_claim: str,
    food: Optional[dict] = None,
    form: Optional[dict] = None,
    dose: Optional[dict] = None,
    frequency: Optional[dict] = None,
    population: Optional[dict] = None,
    component: Optional[dict] = None,
    outcome: Optional[dict] = None,
    is_food_claim: bool = True,
    scope_rejection_reason: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    return {
        "raw_claim": raw_claim,
        "food": food or _absent_slot(),
        "form": form or _absent_slot(),
        "dose": dose or _absent_slot(),
        "frequency": frequency or _absent_slot(),
        "population": population or _absent_slot(),
        "component": component or _absent_slot(),
        "outcome": outcome or _absent_slot(),
        "is_food_claim": is_food_claim,
        "scope_rejection_reason": scope_rejection_reason,
        "notes": notes,
    }


@dataclass
class ExtractionTestCase:
    name: str
    claim: str
    expected_food: Optional[str]
    expected_outcome_present: bool
    expected_ambiguous_slots: set[str]  # subset-check (must include these)
    expected_is_food_claim: bool
    llm_mock_response: dict = field(default_factory=dict)
    expects_error: Optional[type] = None  # e.g., EmptyClaimError


EXTRACTION_TEST_CASES: list[ExtractionTestCase] = [
    ExtractionTestCase(
        name="coffee_vague",
        claim="Is coffee bad for you?",
        expected_food="coffee",
        expected_outcome_present=False,
        expected_ambiguous_slots={"form", "dose", "frequency", "population", "component", "outcome"},
        expected_is_food_claim=True,
        llm_mock_response=_make_pico_dict(
            raw_claim="Is coffee bad for you?",
            food=_explicit("coffee", "coffee"),
        ),
    ),
    ExtractionTestCase(
        name="turmeric_inflammation",
        claim="Is turmeric good for inflammation?",
        expected_food="turmeric",
        expected_outcome_present=True,
        expected_ambiguous_slots={"form", "dose", "population"},
        expected_is_food_claim=True,
        llm_mock_response=_make_pico_dict(
            raw_claim="Is turmeric good for inflammation?",
            food=_explicit("turmeric", "turmeric"),
            outcome=_explicit("inflammation", "inflammation"),
        ),
    ),
    ExtractionTestCase(
        name="coffee_pregnancy_fully_specified",
        claim="Does 2-3 cups of coffee per day during pregnancy cause miscarriage?",
        expected_food="coffee",
        expected_outcome_present=True,
        expected_ambiguous_slots={"component"},
        expected_is_food_claim=True,
        llm_mock_response=_make_pico_dict(
            raw_claim="Does 2-3 cups of coffee per day during pregnancy cause miscarriage?",
            food=_explicit("coffee", "coffee"),
            form=_implied("dietary", "cups of coffee"),
            dose=_explicit("2-3 cups/day", "2-3 cups of coffee per day"),
            frequency=_explicit("daily", "per day"),
            population=_explicit("pregnant", "during pregnancy"),
            outcome=_explicit("miscarriage", "miscarriage"),
        ),
    ),
    ExtractionTestCase(
        name="red_meat_heart",
        claim="Is red meat bad for the heart?",
        expected_food="red meat",
        expected_outcome_present=True,
        expected_ambiguous_slots={"form", "dose"},
        expected_is_food_claim=True,
        llm_mock_response=_make_pico_dict(
            raw_claim="Is red meat bad for the heart?",
            food=_explicit("red meat", "red meat"),
            outcome=_implied("heart disease", "the heart"),
        ),
    ),
    ExtractionTestCase(
        name="processed_meat_cancer",
        claim="I heard processed meat causes cancer. Is that true?",
        expected_food="processed meat",
        expected_outcome_present=True,
        expected_ambiguous_slots={"dose", "population"},
        expected_is_food_claim=True,
        llm_mock_response=_make_pico_dict(
            raw_claim="I heard processed meat causes cancer. Is that true?",
            food=_explicit("processed meat", "processed meat"),
            outcome=_explicit("cancer", "cancer"),
        ),
    ),
    ExtractionTestCase(
        name="aspirin_not_food",
        claim="Is 5mg of aspirin daily good for preventing heart attacks?",
        expected_food=None,
        expected_outcome_present=False,
        expected_ambiguous_slots=set(),  # all absent, but is_food_claim=false
        expected_is_food_claim=False,
        llm_mock_response=_make_pico_dict(
            raw_claim="Is 5mg of aspirin daily good for preventing heart attacks?",
            is_food_claim=False,
            scope_rejection_reason="Aspirin is a drug, not a food or nutrition claim.",
        ),
    ),
    ExtractionTestCase(
        name="curcumin_normalizes_to_turmeric",
        claim="Does a curcumin supplement help with joint pain?",
        expected_food="turmeric",  # normalized from LLM's "curcumin"
        expected_outcome_present=True,
        expected_ambiguous_slots={"dose", "population"},
        expected_is_food_claim=True,
        llm_mock_response=_make_pico_dict(
            raw_claim="Does a curcumin supplement help with joint pain?",
            food=_explicit("curcumin", "curcumin supplement"),
            form=_explicit("supplement", "supplement"),
            component=_explicit("curcumin", "curcumin"),
            outcome=_explicit("joint pain", "joint pain"),
        ),
    ),
    ExtractionTestCase(
        name="alcohol_pregnancy",
        claim="Is alcohol bad during pregnancy?",
        expected_food="alcohol",
        expected_outcome_present=False,  # "bad" is too vague
        expected_ambiguous_slots={"dose", "outcome"},
        expected_is_food_claim=True,
        llm_mock_response=_make_pico_dict(
            raw_claim="Is alcohol bad during pregnancy?",
            food=_explicit("alcohol", "alcohol"),
            population=_explicit("pregnant", "during pregnancy"),
        ),
    ),
    ExtractionTestCase(
        name="intermittent_fasting_weight_loss",
        claim="Does intermittent fasting help with weight loss?",
        expected_food="intermittent fasting",
        expected_outcome_present=True,
        expected_ambiguous_slots={"population", "frequency"},
        expected_is_food_claim=True,
        llm_mock_response=_make_pico_dict(
            raw_claim="Does intermittent fasting help with weight loss?",
            food=_explicit("intermittent fasting", "intermittent fasting"),
            outcome=_explicit("weight loss", "weight loss"),
        ),
    ),
    ExtractionTestCase(
        name="turmeric_typo_normalizes",
        claim="A friend told me tumeric cures cancer",
        expected_food="turmeric",  # fuzzy-normalized from "tumeric"
        expected_outcome_present=True,
        expected_ambiguous_slots={"form", "dose", "population"},
        expected_is_food_claim=True,
        llm_mock_response=_make_pico_dict(
            raw_claim="A friend told me tumeric cures cancer",
            food=_explicit("tumeric", "tumeric"),
            outcome=_explicit("cancer", "cancer"),
        ),
    ),
]

