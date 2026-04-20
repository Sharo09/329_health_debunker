"""Multiple-choice question templates keyed by (slot, food).

Each template is a dict with:
    text:          the question shown to the user
    options:       3-6 human-readable labels
    option_values: internal strings (1:1 with options) used by downstream
                   query construction. The value "unknown" is reserved as
                   the fallback marker — if the user selects an option
                   whose value is "unknown", the elicitor treats it as an
                   "I don't know" answer.
    allow_other:   whether to offer a free-text "Other" fallback
    role:          "pre_retrieval" if the answer materially narrows the
                   PubMed query, "stratifier" if the answer is used
                   post-retrieval to partition/weight papers. Filled in
                   at lookup time from DIMENSION_ROLE; template literals
                   below don't need to carry it.

Templates specific to (slot, food) are preferred; if none exists,
GENERIC_TEMPLATES[slot] is used. Keys for the food component of the
tuple are lowercased canonical forms matching priority_table.py.

Stratifier questions get a suffix hint appended at render time so the
user understands their answer organises results rather than narrowing
the search. See ``render_question_text``.
"""

from typing import TypedDict

from src.elicitation.priority_table import SlotRole, get_slot_role


class QuestionTemplate(TypedDict, total=False):
    # ``total=False`` because the literals below don't carry ``role`` —
    # it's injected at ``get_question`` lookup time from DIMENSION_ROLE.
    # All consumers that call ``get_question`` can rely on ``role``
    # being present on the returned template.
    text: str
    options: list[str]
    option_values: list[str]
    allow_other: bool
    role: SlotRole


STRATIFIER_HINT = (
    " (We'll search broadly and group the results by your answer, so "
    "answering \"not sure\" won't narrow the evidence.)"
)


def render_question_text(template: QuestionTemplate) -> str:
    """Return the final text shown to the user.

    Appends the stratifier-hint suffix when the template's slot role is
    ``stratifier``. Pre-retrieval questions are returned unchanged.
    """
    if template.get("role") == "stratifier":
        return template["text"] + STRATIFIER_HINT
    return template["text"]


QUESTION_TEMPLATES: dict[tuple[str, str], QuestionTemplate] = {
    # ---------- coffee ----------
    ("outcome", "coffee"): {
        "text": "Which health effect of coffee are you asking about?",
        "options": [
            "Heart disease or blood pressure",
            "Cancer risk",
            "Pregnancy or miscarriage",
            "Sleep or anxiety",
            "Longevity / overall mortality",
            "Not sure",
        ],
        "option_values": [
            "cardiovascular disease",
            "cancer",
            "pregnancy outcomes",
            "sleep anxiety",
            "mortality",
            "unknown",
        ],
        "allow_other": True,
    },
    ("population", "coffee"): {
        "text": "Who is the question about?",
        "options": [
            "Healthy adults",
            "Pregnant or breastfeeding",
            "People with heart disease or hypertension",
            "Older adults (65+)",
            "Not sure",
        ],
        "option_values": [
            "healthy adults",
            "pregnant",
            "cardiovascular patients",
            "elderly",
            "unknown",
        ],
        "allow_other": True,
    },
    ("dose", "coffee"): {
        "text": "About how much coffee per day?",
        "options": [
            "Less than 1 cup",
            "1-2 cups",
            "3-4 cups",
            "5 or more cups",
            "Not sure",
        ],
        "option_values": ["low", "moderate", "high", "very high", "unknown"],
        "allow_other": False,
    },
    # ---------- turmeric ----------
    ("form", "turmeric"): {
        "text": "Are you asking about turmeric as food or as a supplement?",
        "options": [
            "As a spice in food (typical culinary amounts)",
            "As a curcumin supplement (standardized extract pills)",
            "Turmeric tea or golden milk",
            "Not sure",
        ],
        "option_values": [
            "dietary",
            "supplement",
            "dietary concentrated",
            "unknown",
        ],
        "allow_other": False,
    },
    ("outcome", "turmeric"): {
        "text": "Which health effect of turmeric are you asking about?",
        "options": [
            "Inflammation (general)",
            "Arthritis or joint pain",
            "Cancer",
            "Liver health",
            "Cognition / memory",
            "Not sure",
        ],
        "option_values": [
            "inflammation",
            "arthritis",
            "cancer",
            "liver health",
            "cognition",
            "unknown",
        ],
        "allow_other": True,
    },
    ("population", "turmeric"): {
        "text": "Who is the question about?",
        "options": [
            "Healthy adults",
            "People with arthritis or inflammatory disease",
            "Pregnant or breastfeeding",
            "Older adults (65+)",
            "Not sure",
        ],
        "option_values": [
            "healthy adults",
            "inflammatory patients",
            "pregnant",
            "elderly",
            "unknown",
        ],
        "allow_other": True,
    },
    # ---------- red meat ----------
    ("outcome", "red meat"): {
        "text": "Which health effect of red meat are you asking about?",
        "options": [
            "Colorectal or other cancer",
            "Heart disease",
            "Type 2 diabetes",
            "Overall mortality",
            "Not sure",
        ],
        "option_values": [
            "colorectal cancer",
            "cardiovascular disease",
            "type 2 diabetes",
            "mortality",
            "unknown",
        ],
        "allow_other": True,
    },
    ("form", "red meat"): {
        "text": "What form of red meat?",
        "options": [
            "Processed (bacon, sausage, deli meats)",
            "Unprocessed (steak, roast, ground beef)",
            "Both / mixed",
            "Not sure",
        ],
        "option_values": ["processed", "unprocessed", "mixed", "unknown"],
        "allow_other": False,
    },
    ("dose", "red meat"): {
        "text": "About how much red meat per week?",
        "options": [
            "Less than 1 serving (rare)",
            "1-3 servings per week",
            "4-6 servings per week",
            "Daily or more",
            "Not sure",
        ],
        "option_values": ["rare", "low", "moderate", "high", "unknown"],
        "allow_other": False,
    },
    # ---------- eggs ----------
    ("outcome", "eggs"): {
        "text": "Which health effect of eggs are you asking about?",
        "options": [
            "Cholesterol levels",
            "Heart disease",
            "Type 2 diabetes",
            "Overall mortality",
            "Not sure",
        ],
        "option_values": [
            "cholesterol",
            "cardiovascular disease",
            "type 2 diabetes",
            "mortality",
            "unknown",
        ],
        "allow_other": True,
    },
    ("population", "eggs"): {
        "text": "Who is the question about?",
        "options": [
            "Healthy adults",
            "People with type 2 diabetes",
            "People with high cholesterol",
            "Children",
            "Not sure",
        ],
        "option_values": [
            "healthy adults",
            "diabetic",
            "hypercholesterolemia",
            "children",
            "unknown",
        ],
        "allow_other": True,
    },
    ("frequency", "eggs"): {
        "text": "How often are eggs eaten?",
        "options": [
            "Rarely (less than 1/week)",
            "A few per week (2-4)",
            "About one per day",
            "Two or more per day",
            "Not sure",
        ],
        "option_values": ["rare", "moderate", "daily", "high", "unknown"],
        "allow_other": False,
    },
    # ---------- alcohol ----------
    ("dose", "alcohol"): {
        "text": "About how much alcohol is consumed?",
        "options": [
            "None / abstainer",
            "Light (up to 1 drink/day)",
            "Moderate (1-2 drinks/day)",
            "Heavy (3+ drinks/day)",
            "Binge (5+ on one occasion)",
            "Not sure",
        ],
        "option_values": [
            "none",
            "light",
            "moderate",
            "heavy",
            "binge",
            "unknown",
        ],
        "allow_other": False,
    },
    ("outcome", "alcohol"): {
        "text": "Which health effect of alcohol are you asking about?",
        "options": [
            "Liver disease",
            "Cancer",
            "Heart disease",
            "Pregnancy / fetal effects",
            "Cognition / dementia",
            "Overall mortality",
            "Not sure",
        ],
        "option_values": [
            "liver disease",
            "cancer",
            "cardiovascular disease",
            "fetal outcomes",
            "cognition",
            "mortality",
            "unknown",
        ],
        "allow_other": True,
    },
    ("population", "alcohol"): {
        "text": "Who is the question about?",
        "options": [
            "Healthy adults",
            "Pregnant or trying to conceive",
            "People with liver disease",
            "Older adults (65+)",
            "Adolescents",
            "Not sure",
        ],
        "option_values": [
            "healthy adults",
            "pregnant",
            "liver patients",
            "elderly",
            "adolescents",
            "unknown",
        ],
        "allow_other": True,
    },
    # ---------- vitamin d ----------
    ("form", "vitamin d"): {
        "text": "What form of vitamin D?",
        "options": [
            "Vitamin D3 (cholecalciferol) supplement",
            "Vitamin D2 (ergocalciferol) supplement",
            "From food (fatty fish, fortified milk)",
            "From sunlight exposure",
            "Not sure",
        ],
        "option_values": [
            "d3 supplement",
            "d2 supplement",
            "dietary",
            "sunlight",
            "unknown",
        ],
        "allow_other": False,
    },
    ("dose", "vitamin d"): {
        "text": "About how much vitamin D per day?",
        "options": [
            "Under 400 IU (low)",
            "400-1000 IU (typical)",
            "1000-4000 IU (moderate-high)",
            "Over 4000 IU (high-dose)",
            "Not sure",
        ],
        "option_values": ["low", "typical", "moderate high", "high dose", "unknown"],
        "allow_other": False,
    },
    ("population", "vitamin d"): {
        "text": "Who is the question about?",
        "options": [
            "Healthy adults with adequate levels",
            "People with vitamin D deficiency",
            "Older adults (65+)",
            "Pregnant or breastfeeding",
            "Children or infants",
            "Not sure",
        ],
        "option_values": [
            "healthy replete",
            "deficient",
            "elderly",
            "pregnant",
            "children",
            "unknown",
        ],
        "allow_other": True,
    },
    # ---------- intermittent fasting ----------
    ("population", "intermittent fasting"): {
        "text": "Who is the question about?",
        "options": [
            "Healthy adults wanting weight loss",
            "People with type 2 diabetes or insulin resistance",
            "People with overweight / obesity",
            "Older adults (65+)",
            "Not sure",
        ],
        "option_values": [
            "healthy adults",
            "diabetic",
            "obese",
            "elderly",
            "unknown",
        ],
        "allow_other": True,
    },
    ("outcome", "intermittent fasting"): {
        "text": "Which outcome of intermittent fasting are you asking about?",
        "options": [
            "Weight loss / body composition",
            "Blood sugar / insulin sensitivity",
            "Longevity / metabolic health",
            "Cognition / brain health",
            "Not sure",
        ],
        "option_values": [
            "weight loss",
            "glucose metabolism",
            "longevity",
            "cognition",
            "unknown",
        ],
        "allow_other": True,
    },
    ("frequency", "intermittent fasting"): {
        "text": "Which fasting schedule?",
        "options": [
            "Time-restricted eating (e.g., 16:8 daily)",
            "5:2 (two low-calorie days per week)",
            "Alternate-day fasting",
            "Extended fasts (24h+ occasionally)",
            "Not sure",
        ],
        "option_values": [
            "time restricted 16 8",
            "five two",
            "alternate day",
            "extended",
            "unknown",
        ],
        "allow_other": True,
    },
    # ---------- artificial sweeteners ----------
    ("outcome", "artificial sweeteners"): {
        "text": "Which health effect of artificial sweeteners are you asking about?",
        "options": [
            "Cancer risk",
            "Blood sugar / diabetes",
            "Weight gain / obesity",
            "Gut microbiome",
            "Heart disease",
            "Not sure",
        ],
        "option_values": [
            "cancer",
            "glucose metabolism",
            "weight gain",
            "microbiome",
            "cardiovascular disease",
            "unknown",
        ],
        "allow_other": True,
    },
    ("population", "artificial sweeteners"): {
        "text": "Who is the question about?",
        "options": [
            "Healthy adults",
            "People with diabetes",
            "Children",
            "Pregnant or breastfeeding",
            "Not sure",
        ],
        "option_values": [
            "healthy adults",
            "diabetic",
            "children",
            "pregnant",
            "unknown",
        ],
        "allow_other": True,
    },
    ("dose", "artificial sweeteners"): {
        "text": "About how much do they consume?",
        "options": [
            "Occasional (a few times a week)",
            "Daily low amount (e.g., one diet drink)",
            "Daily high amount (multiple diet drinks)",
            "Not sure",
        ],
        "option_values": ["occasional", "low daily", "high daily", "unknown"],
        "allow_other": False,
    },
    # ---------- added sugar ----------
    ("outcome", "added sugar"): {
        "text": "Which health effect of added sugar are you asking about?",
        "options": [
            "Weight gain / obesity",
            "Type 2 diabetes",
            "Dental caries",
            "Heart disease",
            "Fatty liver (NAFLD)",
            "Not sure",
        ],
        "option_values": [
            "weight gain",
            "type 2 diabetes",
            "dental caries",
            "cardiovascular disease",
            "fatty liver",
            "unknown",
        ],
        "allow_other": True,
    },
    ("dose", "added sugar"): {
        "text": "About how much added sugar?",
        "options": [
            "Under 25 g/day (low)",
            "25-50 g/day (moderate)",
            "50-100 g/day (high)",
            "Over 100 g/day (very high)",
            "Not sure",
        ],
        "option_values": ["low", "moderate", "high", "very high", "unknown"],
        "allow_other": False,
    },
    ("population", "added sugar"): {
        "text": "Who is the question about?",
        "options": [
            "Healthy adults",
            "Children or adolescents",
            "People with overweight / obesity",
            "People with type 2 diabetes",
            "Not sure",
        ],
        "option_values": [
            "healthy adults",
            "children",
            "obese",
            "diabetic",
            "unknown",
        ],
        "allow_other": True,
    },
    # ---------- dairy milk ----------
    ("population", "dairy milk"): {
        "text": "Who is the question about?",
        "options": [
            "Healthy adults",
            "Children or adolescents",
            "Infants",
            "Older adults (65+)",
            "People with lactose intolerance",
            "Not sure",
        ],
        "option_values": [
            "healthy adults",
            "children",
            "infants",
            "elderly",
            "lactose intolerant",
            "unknown",
        ],
        "allow_other": True,
    },
    ("outcome", "dairy milk"): {
        "text": "Which health effect of dairy milk are you asking about?",
        "options": [
            "Bone health / osteoporosis",
            "Prostate or other cancer",
            "Heart disease",
            "Allergy or digestive issues",
            "Growth / child development",
            "Not sure",
        ],
        "option_values": [
            "bone health",
            "cancer",
            "cardiovascular disease",
            "allergy gi",
            "growth development",
            "unknown",
        ],
        "allow_other": True,
    },
    ("form", "dairy milk"): {
        "text": "What form of dairy milk?",
        "options": [
            "Whole milk",
            "Low-fat or skim milk",
            "Raw (unpasteurized) milk",
            "Any / mixed",
            "Not sure",
        ],
        "option_values": ["whole", "low fat", "raw", "mixed", "unknown"],
        "allow_other": False,
    },
}


GENERIC_TEMPLATES: dict[str, QuestionTemplate] = {
    "outcome": {
        "text": "Which health effect are you asking about?",
        "options": [
            "Heart disease",
            "Cancer",
            "Diabetes or blood sugar",
            "Overall mortality / longevity",
            "Not sure",
        ],
        "option_values": [
            "cardiovascular disease",
            "cancer",
            "type 2 diabetes",
            "mortality",
            "unknown",
        ],
        "allow_other": True,
    },
    "population": {
        "text": "Who is this question about?",
        "options": [
            "Healthy adults",
            "Pregnant or breastfeeding",
            "Children",
            "Older adults (65+)",
            "Someone with a specific condition",
            "Not sure",
        ],
        "option_values": [
            "healthy adults",
            "pregnant",
            "children",
            "elderly",
            "condition",
            "unknown",
        ],
        "allow_other": True,
    },
    "form": {
        "text": "In what form?",
        "options": [
            "As ordinary food",
            "As a supplement or pill",
            "As an extract or concentrated product",
            "Not sure",
        ],
        "option_values": ["dietary", "supplement", "extract", "unknown"],
        "allow_other": True,
    },
    "dose": {
        "text": "About how much?",
        "options": [
            "A small amount",
            "A moderate amount",
            "A large amount",
            "Not sure",
        ],
        "option_values": ["low", "moderate", "high", "unknown"],
        "allow_other": True,
    },
    "frequency": {
        "text": "How often is it consumed?",
        "options": [
            "Occasionally (less than weekly)",
            "Weekly",
            "Daily",
            "Multiple times per day",
            "Not sure",
        ],
        "option_values": ["occasional", "weekly", "daily", "multi daily", "unknown"],
        "allow_other": False,
    },
    "component": {
        "text": "Which specific component are you asking about?",
        "options": [
            "The whole food itself",
            "A specific active compound",
            "Not sure",
        ],
        "option_values": ["whole_food", "active compound", "unknown"],
        "allow_other": True,
    },
}


FALLBACK_VALUE = "unknown"


def get_question(slot: str, food: str | None) -> QuestionTemplate:
    """Return the template for (slot, food); else the generic template for slot.

    Food lookup is case-insensitive with whitespace trimming. Raises
    KeyError if no specific template exists and the slot has no generic
    fallback either.

    The returned template:

    - carries a ``role`` field derived from ``DIMENSION_ROLE`` in
      priority_table.py — so callers never have to duplicate the
      classification logic.
    - for stratifier slots, has the stratifier-hint suffix already
      appended to ``text`` so UI adapters can show it unchanged.

    The module-level dicts are never mutated — every call returns a
    fresh copy with role/text injected.
    """
    base: QuestionTemplate | None = None

    if food:
        key = (slot, food.strip().lower())
        if key in QUESTION_TEMPLATES:
            base = QUESTION_TEMPLATES[key]

    if base is None and slot in GENERIC_TEMPLATES:
        base = GENERIC_TEMPLATES[slot]

    if base is None:
        raise KeyError(
            f"No template defined for slot={slot!r} (food={food!r}) and no generic fallback."
        )

    role: SlotRole = get_slot_role(slot)
    enriched: QuestionTemplate = {
        "text": base["text"],
        "options": list(base["options"]),
        "option_values": list(base["option_values"]),
        "allow_other": base["allow_other"],
        "role": role,
    }
    enriched["text"] = render_question_text(enriched)
    return enriched
