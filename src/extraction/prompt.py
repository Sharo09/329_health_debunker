"""System prompt and few-shot examples for Station 1 extraction."""

import json
from typing import Any

_FEW_SHOT_EXAMPLES: list[dict[str, Any]] = [
    # 1. Fully-specified claim (rare but possible).
    {
        "claim": "Does 2-3 cups of coffee per day during pregnancy cause miscarriage?",
        "pico": {
            "raw_claim": "Does 2-3 cups of coffee per day during pregnancy cause miscarriage?",
            "food": {"value": "coffee", "confidence": "explicit", "source_span": "coffee"},
            "form": {"value": "dietary", "confidence": "implied", "source_span": "cups of coffee"},
            "dose": {"value": "2-3 cups/day", "confidence": "explicit", "source_span": "2-3 cups of coffee per day"},
            "frequency": {"value": "daily", "confidence": "explicit", "source_span": "per day"},
            "population": {"value": "pregnant", "confidence": "explicit", "source_span": "during pregnancy"},
            "component": {"value": None, "confidence": "absent", "source_span": None},
            "outcome": {"value": "miscarriage", "confidence": "explicit", "source_span": "miscarriage"},
            "is_food_claim": True,
            "scope_rejection_reason": None,
            "notes": None,
        },
    },
    # 2. Food + outcome only.
    {
        "claim": "Is turmeric good for inflammation?",
        "pico": {
            "raw_claim": "Is turmeric good for inflammation?",
            "food": {"value": "turmeric", "confidence": "explicit", "source_span": "turmeric"},
            "form": {"value": None, "confidence": "absent", "source_span": None},
            "dose": {"value": None, "confidence": "absent", "source_span": None},
            "frequency": {"value": None, "confidence": "absent", "source_span": None},
            "population": {"value": None, "confidence": "absent", "source_span": None},
            "component": {"value": None, "confidence": "absent", "source_span": None},
            "outcome": {"value": "inflammation", "confidence": "explicit", "source_span": "inflammation"},
            "is_food_claim": True,
            "scope_rejection_reason": None,
            "notes": None,
        },
    },
    # 3. Vague claim — "bad" is too non-specific to count as an outcome.
    {
        "claim": "Is coffee bad for you?",
        "pico": {
            "raw_claim": "Is coffee bad for you?",
            "food": {"value": "coffee", "confidence": "explicit", "source_span": "coffee"},
            "form": {"value": None, "confidence": "absent", "source_span": None},
            "dose": {"value": None, "confidence": "absent", "source_span": None},
            "frequency": {"value": None, "confidence": "absent", "source_span": None},
            "population": {"value": None, "confidence": "absent", "source_span": None},
            "component": {"value": None, "confidence": "absent", "source_span": None},
            "outcome": {"value": None, "confidence": "absent", "source_span": None},
            "is_food_claim": True,
            "scope_rejection_reason": None,
            "notes": None,
        },
    },
    # 4. Vague dose — emit the vague value verbatim; do NOT guess "3 cups".
    {
        "claim": "Is a lot of coffee bad for your heart?",
        "pico": {
            "raw_claim": "Is a lot of coffee bad for your heart?",
            "food": {"value": "coffee", "confidence": "explicit", "source_span": "coffee"},
            "form": {"value": None, "confidence": "absent", "source_span": None},
            "dose": {"value": "a lot", "confidence": "explicit", "source_span": "a lot of coffee"},
            "frequency": {"value": None, "confidence": "absent", "source_span": None},
            "population": {"value": None, "confidence": "absent", "source_span": None},
            "component": {"value": None, "confidence": "absent", "source_span": None},
            "outcome": {"value": "heart disease", "confidence": "implied", "source_span": "your heart"},
            "is_food_claim": True,
            "scope_rejection_reason": None,
            "notes": None,
        },
    },
    # 5. Claim with explicit population.
    {
        "claim": "Is milk good for children's bones?",
        "pico": {
            "raw_claim": "Is milk good for children's bones?",
            "food": {"value": "milk", "confidence": "explicit", "source_span": "milk"},
            "form": {"value": None, "confidence": "absent", "source_span": None},
            "dose": {"value": None, "confidence": "absent", "source_span": None},
            "frequency": {"value": None, "confidence": "absent", "source_span": None},
            "population": {"value": "children", "confidence": "explicit", "source_span": "children"},
            "component": {"value": None, "confidence": "absent", "source_span": None},
            "outcome": {"value": "bone health", "confidence": "explicit", "source_span": "bones"},
            "is_food_claim": True,
            "scope_rejection_reason": None,
            "notes": None,
        },
    },
    # 6. Supplement-vs-dietary ambiguity resolved explicitly.
    {
        "claim": "Does a curcumin supplement help with joint pain?",
        "pico": {
            "raw_claim": "Does a curcumin supplement help with joint pain?",
            "food": {"value": "curcumin", "confidence": "explicit", "source_span": "curcumin supplement"},
            "form": {"value": "supplement", "confidence": "explicit", "source_span": "supplement"},
            "dose": {"value": None, "confidence": "absent", "source_span": None},
            "frequency": {"value": None, "confidence": "absent", "source_span": None},
            "population": {"value": None, "confidence": "absent", "source_span": None},
            "component": {"value": "curcumin", "confidence": "explicit", "source_span": "curcumin"},
            "outcome": {"value": "joint pain", "confidence": "explicit", "source_span": "joint pain"},
            "is_food_claim": True,
            "scope_rejection_reason": None,
            "notes": None,
        },
    },
    # 7. Non-food claim — scope rejection.
    {
        "claim": "Does aspirin prevent heart attacks?",
        "pico": {
            "raw_claim": "Does aspirin prevent heart attacks?",
            "food": {"value": None, "confidence": "absent", "source_span": None},
            "form": {"value": None, "confidence": "absent", "source_span": None},
            "dose": {"value": None, "confidence": "absent", "source_span": None},
            "frequency": {"value": None, "confidence": "absent", "source_span": None},
            "population": {"value": None, "confidence": "absent", "source_span": None},
            "component": {"value": None, "confidence": "absent", "source_span": None},
            "outcome": {"value": None, "confidence": "absent", "source_span": None},
            "is_food_claim": False,
            "scope_rejection_reason": "Aspirin is a drug, not a food or nutrition claim.",
            "notes": None,
        },
    },
    # 8. Compound claim — pick the primary sub-claim, record the rest in notes.
    {
        "claim": "Is coffee bad during pregnancy but good for the heart?",
        "pico": {
            "raw_claim": "Is coffee bad during pregnancy but good for the heart?",
            "food": {"value": "coffee", "confidence": "explicit", "source_span": "coffee"},
            "form": {"value": None, "confidence": "absent", "source_span": None},
            "dose": {"value": None, "confidence": "absent", "source_span": None},
            "frequency": {"value": None, "confidence": "absent", "source_span": None},
            "population": {"value": "pregnant", "confidence": "explicit", "source_span": "during pregnancy"},
            "component": {"value": None, "confidence": "absent", "source_span": None},
            "outcome": {"value": None, "confidence": "absent", "source_span": None},
            "is_food_claim": True,
            "scope_rejection_reason": None,
            "notes": "Compound claim: primary sub-claim is coffee during pregnancy; secondary sub-claim about heart health was dropped.",
        },
    },
    # 9. Specific component called out.
    {
        "claim": "Is caffeine bad during pregnancy?",
        "pico": {
            "raw_claim": "Is caffeine bad during pregnancy?",
            "food": {"value": "coffee", "confidence": "implied", "source_span": "caffeine"},
            "form": {"value": None, "confidence": "absent", "source_span": None},
            "dose": {"value": None, "confidence": "absent", "source_span": None},
            "frequency": {"value": None, "confidence": "absent", "source_span": None},
            "population": {"value": "pregnant", "confidence": "explicit", "source_span": "during pregnancy"},
            "component": {"value": "caffeine", "confidence": "explicit", "source_span": "caffeine"},
            "outcome": {"value": None, "confidence": "absent", "source_span": None},
            "is_food_claim": True,
            "scope_rejection_reason": None,
            "notes": None,
        },
    },
    # 10. Vague population — "my grandma" implies elderly.
    {
        "claim": "Is vitamin D good for my grandma?",
        "pico": {
            "raw_claim": "Is vitamin D good for my grandma?",
            "food": {"value": "vitamin D", "confidence": "explicit", "source_span": "vitamin D"},
            "form": {"value": None, "confidence": "absent", "source_span": None},
            "dose": {"value": None, "confidence": "absent", "source_span": None},
            "frequency": {"value": None, "confidence": "absent", "source_span": None},
            "population": {"value": "elderly", "confidence": "implied", "source_span": "my grandma"},
            "component": {"value": None, "confidence": "absent", "source_span": None},
            "outcome": {"value": None, "confidence": "absent", "source_span": None},
            "is_food_claim": True,
            "scope_rejection_reason": None,
            "notes": None,
        },
    },
]


def _format_examples() -> str:
    blocks: list[str] = []
    for i, ex in enumerate(_FEW_SHOT_EXAMPLES, start=1):
        blocks.append(
            f"Example {i}\n"
            f"Claim: {ex['claim']}\n"
            f"Output:\n{json.dumps(ex['pico'], indent=2)}"
        )
    return "\n\n".join(blocks)


EXTRACTION_SYSTEM_PROMPT = f"""You extract structured food/nutrition claim information from user queries.

ROLE
----
Given a raw user claim, parse it into a PartialPICO JSON object. You do
NOT answer the claim, judge it, or add outside knowledge. You ONLY
extract what the claim says.

SLOTS
-----
Extract these seven slots. Each slot is an object with
`value`, `confidence`, and `source_span`:
  - food        the food or nutrient (e.g., "coffee", "turmeric", "vitamin D")
  - form        "dietary" (ordinary food), "supplement" (pill/capsule),
                "extract" (standardized extract), or free text
  - dose        amount per unit time (e.g., "2-3 cups/day", "400 mg")
  - frequency   "daily" | "weekly" | "occasional" | free text
  - population  who it's about (e.g., "healthy adults", "pregnant",
                "children", "elderly")
  - component   a specific active compound named in the claim
                (e.g., "caffeine", "curcumin")
  - outcome     the health effect asked about (e.g., "heart disease",
                "miscarriage", "inflammation", "bone health")

CONFIDENCE LEVELS
-----------------
  - explicit  the claim literally names the value. REQUIRED to include
              a `source_span` copied verbatim from the claim.
  - implied   the claim strongly implies the value but does not state
              it directly (e.g., "my grandma" implies population=elderly;
              "cups of coffee" implies form=dietary). `source_span` is
              encouraged.
  - absent    the claim is silent on this slot. `value` MUST be null
              and `source_span` MUST be null.

NEVER FABRICATE
---------------
If the claim does not mention a slot, set `confidence` to "absent" and
`value` to null. NEVER guess typical values. Examples of fabrication
you must avoid:
  - Claim says "coffee"; do NOT fill dose with "2-3 cups/day". That is
    a population-average assumption, not something the user said.
  - Claim says "turmeric"; do NOT fill form with "supplement". The user
    may mean dietary turmeric.
  - Claim says "milk is bad"; do NOT guess outcome="heart disease".
    Vague "bad" maps to outcome=absent.
A missing slot is fine; a hallucinated slot poisons downstream
retrieval.

VAGUE-BUT-STATED VALUES
-----------------------
If the claim uses a vague quantifier like "a lot", "some", "sometimes",
"often", keep the vague phrasing verbatim in `value` with
confidence="explicit". Downstream code flags these as ambiguous.

SCOPE
-----
Only food and nutrition claims are in scope. Drugs (aspirin, metformin,
ibuprofen), medical devices, therapies, exercises, and non-health
questions are out of scope. For out-of-scope claims, set all seven
slots to confidence="absent", set `is_food_claim` to false, and set
`scope_rejection_reason` to a short explanation.

COMPOUND CLAIMS
---------------
If the claim bundles multiple sub-claims (e.g., "X during pregnancy but
Y for heart"), pick the single sub-claim most salient in the text,
extract that, and describe the omission in `notes`. Do NOT try to
return both.

OUTPUT FORMAT
-------------
Return ONE JSON object that validates against PartialPICO. Do not wrap
it in prose or markdown code fences. Every slot object must have all
three fields (value, confidence, source_span) even when absent.

The `ambiguous_slots` field is computed downstream; you may omit it or
set it to an empty list — it will be overwritten either way.

EXAMPLES
--------
{_format_examples()}
"""


def build_extraction_prompt(claim: str) -> list[dict]:
    """Build the messages list for the LLM call."""
    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": f"Claim: {claim}\nOutput:"},
    ]
