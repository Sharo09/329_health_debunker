"""End-to-end integration tests across all 10 demo foods (Task 6).

For each food we:
  1. Mock Station 1's extraction output as a PartialPICO.
  2. Run elicitation with scripted answers.
  3. Assert the LockedPICO matches the expected per-slot values.
  4. Assert the MeSH terms Station 3 would need to build a PubMed query
     are all derivable from the LockedPICO via a small lookup map.
"""

from dataclasses import dataclass, field

import pytest

from src.elicitation.elicitor import ElicitationAgent
from src.schemas import LockedPICO, PartialPICO
from tests.fixtures import MockUIAdapter


# Map from (slot, internal_value) or food -> MeSH term(s). This is a
# miniature of the logic Station 3 will own; the integration test asserts
# every expected MeSH term for a locked PICO is producible here.

FOOD_TO_MESH: dict[str, str] = {
    "coffee": "Coffee",
    "turmeric": "Curcuma",
    "red meat": "Red Meat",
    "eggs": "Eggs",
    "alcohol": "Alcohol Drinking",
    "vitamin d": "Vitamin D",
    "intermittent fasting": "Intermittent Fasting",
    "artificial sweeteners": "Sweetening Agents",
    "added sugar": "Dietary Sugars",
    "dairy milk": "Milk",
}

# Form refinements that replace or supplement the food MeSH term.
FORM_OVERRIDE_TO_MESH: dict[tuple[str, str], str] = {
    ("turmeric", "supplement"): "Curcumin",
    ("turmeric", "dietary_concentrated"): "Curcumin",
    ("vitamin d", "d3_supplement"): "Cholecalciferol",
    ("vitamin d", "d2_supplement"): "Ergocalciferols",
    ("red meat", "processed"): "Meat Products",
}

OUTCOME_TO_MESH: dict[str, str] = {
    "cardiovascular_disease": "Cardiovascular Diseases",
    "cancer": "Neoplasms",
    "colorectal_cancer": "Colorectal Neoplasms",
    "pregnancy_outcomes": "Pregnancy Outcome",
    "fetal_outcomes": "Fetal Development",
    "sleep_anxiety": "Sleep",
    "mortality": "Mortality",
    "inflammation": "Inflammation",
    "arthritis": "Arthritis",
    "liver_health": "Liver Diseases",
    "liver_disease": "Liver Diseases",
    "cognition": "Cognition",
    "cholesterol": "Cholesterol",
    "type_2_diabetes": "Diabetes Mellitus, Type 2",
    "glucose_metabolism": "Blood Glucose",
    "weight_loss": "Weight Loss",
    "weight_gain": "Weight Gain",
    "longevity": "Longevity",
    "dental_caries": "Dental Caries",
    "fatty_liver": "Non-alcoholic Fatty Liver Disease",
    "microbiome": "Gastrointestinal Microbiome",
    "bone_health": "Bone Density",
    "allergy_gi": "Food Hypersensitivity",
    "growth_development": "Child Development",
}

POPULATION_TO_MESH: dict[str, str] = {
    "healthy_adults": "Adult",
    "pregnant": "Pregnancy",
    "children": "Child",
    "infants": "Infant",
    "elderly": "Aged",
    "adolescents": "Adolescent",
    "diabetic": "Diabetes Mellitus, Type 2",
    "obese": "Obesity",
    "hypercholesterolemia": "Hypercholesterolemia",
    "deficient": "Vitamin D Deficiency",
    "healthy_replete": "Adult",
    "cardiovascular_patients": "Cardiovascular Diseases",
    "inflammatory_patients": "Inflammation",
    "liver_patients": "Liver Diseases",
    "lactose_intolerant": "Lactose Intolerance",
    "condition": "Adult",
}


def derive_mesh_terms(locked: LockedPICO) -> set[str]:
    """Derive the MeSH terms a PubMed query would use from a LockedPICO."""
    terms: set[str] = set()

    food_key = (locked.food or "").strip().lower()

    # Form-refined food term wins over the generic food term.
    form_key = (food_key, locked.form)
    if form_key in FORM_OVERRIDE_TO_MESH:
        terms.add(FORM_OVERRIDE_TO_MESH[form_key])
    elif food_key in FOOD_TO_MESH:
        terms.add(FOOD_TO_MESH[food_key])

    if locked.outcome in OUTCOME_TO_MESH:
        terms.add(OUTCOME_TO_MESH[locked.outcome])

    if locked.population in POPULATION_TO_MESH:
        terms.add(POPULATION_TO_MESH[locked.population])

    return terms


@dataclass
class Scenario:
    name: str
    partial: PartialPICO
    answers: list[tuple[str, str]]
    expected_slots_asked: list[str]
    expected_locked: dict
    expected_mesh: set[str]
    allow_extra_mesh: bool = True
    fallbacks_expected: list[str] = field(default_factory=list)


SCENARIOS: list[Scenario] = [
    Scenario(
        name="coffee",
        partial=PartialPICO(
            raw_claim="Is coffee bad for you?",
            food="coffee",
            ambiguous_slots=["outcome", "population", "dose"],
        ),
        answers=[
            ("Heart disease or blood pressure", "cardiovascular_disease"),
            ("Healthy adults", "healthy_adults"),
            ("1-2 cups", "moderate"),
        ],
        expected_slots_asked=["outcome", "population", "dose"],
        expected_locked={
            "food": "coffee",
            "outcome": "cardiovascular_disease",
            "population": "healthy_adults",
            "dose": "moderate",
        },
        expected_mesh={"Coffee", "Cardiovascular Diseases", "Adult"},
    ),
    Scenario(
        name="turmeric",
        partial=PartialPICO(
            raw_claim="Does turmeric reduce inflammation?",
            food="turmeric",
            ambiguous_slots=["form", "outcome", "population"],
        ),
        answers=[
            ("As a curcumin supplement (standardized extract pills)", "supplement"),
            ("Inflammation (general)", "inflammation"),
            ("People with arthritis or inflammatory disease", "inflammatory_patients"),
        ],
        expected_slots_asked=["form", "outcome", "population"],
        expected_locked={
            "food": "turmeric",
            "form": "supplement",
            "outcome": "inflammation",
            "population": "inflammatory_patients",
        },
        expected_mesh={"Curcumin", "Inflammation"},
    ),
    Scenario(
        name="red meat",
        partial=PartialPICO(
            raw_claim="Does red meat cause cancer?",
            food="red meat",
            ambiguous_slots=["outcome", "form", "dose"],
        ),
        answers=[
            ("Colorectal or other cancer", "colorectal_cancer"),
            ("Processed (bacon, sausage, deli meats)", "processed"),
            ("Daily or more", "high"),
        ],
        expected_slots_asked=["outcome", "form", "dose"],
        expected_locked={
            "food": "red meat",
            "outcome": "colorectal_cancer",
            "form": "processed",
            "dose": "high",
        },
        expected_mesh={"Meat Products", "Colorectal Neoplasms", "Adult"},
        fallbacks_expected=["population"],  # population defaulted
    ),
    Scenario(
        name="eggs",
        partial=PartialPICO(
            raw_claim="Are eggs bad for cholesterol?",
            food="eggs",
            ambiguous_slots=["outcome", "population", "frequency"],
        ),
        answers=[
            ("Cholesterol levels", "cholesterol"),
            ("People with type 2 diabetes", "diabetic"),
            ("About one per day", "daily"),
        ],
        expected_slots_asked=["outcome", "population", "frequency"],
        expected_locked={
            "food": "eggs",
            "outcome": "cholesterol",
            "population": "diabetic",
            "frequency": "daily",
        },
        expected_mesh={"Eggs", "Cholesterol", "Diabetes Mellitus, Type 2"},
    ),
    Scenario(
        name="alcohol",
        partial=PartialPICO(
            raw_claim="Is a glass of wine a day good for the heart?",
            food="alcohol",
            ambiguous_slots=["dose", "outcome", "population"],
        ),
        answers=[
            ("Light (up to 1 drink/day)", "light"),
            ("Heart disease", "cardiovascular_disease"),
            ("Healthy adults", "healthy_adults"),
        ],
        expected_slots_asked=["dose", "outcome", "population"],
        expected_locked={
            "food": "alcohol",
            "dose": "light",
            "outcome": "cardiovascular_disease",
            "population": "healthy_adults",
        },
        expected_mesh={"Alcohol Drinking", "Cardiovascular Diseases", "Adult"},
    ),
    Scenario(
        # Vitamin D's priority is [form, dose, population] — outcome is
        # NOT in the priority list, so Station 1 must pre-extract it or
        # elicitation will fail with InsufficientElicitationError.
        name="vitamin d",
        partial=PartialPICO(
            raw_claim="Does vitamin D prevent osteoporosis?",
            food="vitamin d",
            outcome="bone_health",
            ambiguous_slots=["form", "dose", "population"],
        ),
        answers=[
            ("Vitamin D3 (cholecalciferol) supplement", "d3_supplement"),
            ("1000-4000 IU (moderate-high)", "moderate_high"),
            ("People with vitamin D deficiency", "deficient"),
        ],
        expected_slots_asked=["form", "dose", "population"],
        expected_locked={
            "food": "vitamin d",
            "form": "d3_supplement",
            "dose": "moderate_high",
            "population": "deficient",
            "outcome": "bone_health",
        },
        expected_mesh={"Cholecalciferol", "Vitamin D Deficiency", "Bone Density"},
    ),
    Scenario(
        name="intermittent fasting",
        partial=PartialPICO(
            raw_claim="Does intermittent fasting help lose weight?",
            food="intermittent fasting",
            ambiguous_slots=["population", "outcome", "frequency"],
        ),
        answers=[
            ("People with overweight / obesity", "obese"),
            ("Weight loss / body composition", "weight_loss"),
            ("Time-restricted eating (e.g., 16:8 daily)", "time_restricted_16_8"),
        ],
        expected_slots_asked=["population", "outcome", "frequency"],
        expected_locked={
            "food": "intermittent fasting",
            "population": "obese",
            "outcome": "weight_loss",
            "frequency": "time_restricted_16_8",
        },
        expected_mesh={"Intermittent Fasting", "Weight Loss", "Obesity"},
    ),
    Scenario(
        name="artificial sweeteners",
        partial=PartialPICO(
            raw_claim="Do artificial sweeteners cause cancer?",
            food="artificial sweeteners",
            ambiguous_slots=["outcome", "population", "dose"],
        ),
        answers=[
            ("Cancer risk", "cancer"),
            ("Healthy adults", "healthy_adults"),
            ("Daily high amount (multiple diet drinks)", "high_daily"),
        ],
        expected_slots_asked=["outcome", "population", "dose"],
        expected_locked={
            "food": "artificial sweeteners",
            "outcome": "cancer",
            "population": "healthy_adults",
            "dose": "high_daily",
        },
        expected_mesh={"Sweetening Agents", "Neoplasms", "Adult"},
    ),
    Scenario(
        name="added sugar",
        partial=PartialPICO(
            raw_claim="Does sugar cause diabetes?",
            food="added sugar",
            ambiguous_slots=["outcome", "dose", "population"],
        ),
        answers=[
            ("Type 2 diabetes", "type_2_diabetes"),
            ("50-100 g/day (high)", "high"),
            ("Healthy adults", "healthy_adults"),
        ],
        expected_slots_asked=["outcome", "dose", "population"],
        expected_locked={
            "food": "added sugar",
            "outcome": "type_2_diabetes",
            "dose": "high",
            "population": "healthy_adults",
        },
        expected_mesh={"Dietary Sugars", "Diabetes Mellitus, Type 2", "Adult"},
    ),
    Scenario(
        name="dairy milk",
        partial=PartialPICO(
            raw_claim="Is milk good for kids' bones?",
            food="dairy milk",
            ambiguous_slots=["population", "outcome", "form"],
        ),
        answers=[
            ("Children or adolescents", "children"),
            ("Bone health / osteoporosis", "bone_health"),
            ("Whole milk", "whole"),
        ],
        expected_slots_asked=["population", "outcome", "form"],
        expected_locked={
            "food": "dairy milk",
            "population": "children",
            "outcome": "bone_health",
            "form": "whole",
        },
        expected_mesh={"Milk", "Bone Density", "Child"},
    ),
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_end_to_end_elicitation_per_food(scenario: Scenario, tmp_path):
    adapter = MockUIAdapter(scenario.answers)
    log_file = tmp_path / "elicit.jsonl"
    agent = ElicitationAgent(adapter, log_file=str(log_file))

    locked = agent.elicit(scenario.partial)

    # 1. Required slots are filled.
    assert locked.food is not None
    assert locked.outcome is not None
    assert locked.population is not None
    assert locked.locked is True

    # 2. Specific values match expectations.
    for slot, expected in scenario.expected_locked.items():
        actual = getattr(locked, slot)
        assert actual == expected, (
            f"{scenario.name}: slot={slot} expected={expected!r} got={actual!r}"
        )

    # 3. Slots asked match expectations (and count is within cap).
    assert len(adapter.asked_questions) == len(scenario.expected_slots_asked)
    assert len(adapter.asked_questions) <= ElicitationAgent.MAX_QUESTIONS

    # 4. Fallbacks as expected.
    for slot in scenario.fallbacks_expected:
        assert slot in locked.fallbacks_used, (
            f"{scenario.name}: expected {slot} in fallbacks_used, got {locked.fallbacks_used}"
        )

    # 5. MeSH terms derivable from locked PICO.
    derived = derive_mesh_terms(locked)
    missing = scenario.expected_mesh - derived
    assert not missing, (
        f"{scenario.name}: missing MeSH terms {missing} (derived={derived})"
    )


def test_all_ten_demo_foods_covered():
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
    assert {s.name for s in SCENARIOS} == expected
