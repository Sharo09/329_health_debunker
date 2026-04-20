"""F1 — deterministic dose-plausibility check.

Two halves:

1. ``parse_dose`` uses the shared ``LLMClient`` to turn the free-text
   ``dose`` field on a ``PartialPICO`` into a structured ``ParsedDose``.
   Returns ``None`` when the dose is empty or cannot be parsed; callers
   treat missing parses as "skip F1".
2. ``check_dose_plausibility`` is pure arithmetic against
   ``ReferenceEntry`` thresholds. No LLM involved.

The split keeps the judgment (parse) and the rule (compare) separable,
so the comparison is trivially unit-testable without any LLM.
"""

from __future__ import annotations

from typing import Optional

from src.plausibility.reference_table import ReferenceEntry, ReferenceTable
from src.plausibility.schemas import ParsedDose, PlausibilityFailure


DOSE_PARSE_SYSTEM_PROMPT = """\
Parse a dose expression from a health claim into a structured form.

You receive two inputs:
  raw_dose: a free-text dose string (may be empty or vague)
  food: the food or substance the dose refers to, for disambiguation

Return:
  numeric_value     the numeric quantity stated, or null if none
  unit              the unit as stated or naturally implied, or null
  time_basis        "per day", "per week", "per meal", "total", null
  confidence        "high"   - numeric + unit + time basis all clear
                    "medium" - two of three clear
                    "low"    - only a number, no unit or basis
                    "not_a_dose" - vague phrase like "a lot" / "some"
  raw_source        the original raw_dose string verbatim

Examples:

Input:  raw_dose="100 apples per day", food="apple"
Output: {
  "numeric_value": 100,
  "unit": "apple",
  "time_basis": "per day",
  "confidence": "high",
  "raw_source": "100 apples per day"
}

Input:  raw_dose="50000 IU", food="vitamin D"
Output: {
  "numeric_value": 50000,
  "unit": "IU",
  "time_basis": "per day",
  "confidence": "high",
  "raw_source": "50000 IU"
}

Input:  raw_dose="a lot of coffee", food="coffee"
Output: {
  "numeric_value": null,
  "unit": null,
  "time_basis": null,
  "confidence": "not_a_dose",
  "raw_source": "a lot of coffee"
}

Input:  raw_dose="2-3 cups/day", food="coffee"
Output: {
  "numeric_value": 2.5,
  "unit": "cup",
  "time_basis": "per day",
  "confidence": "high",
  "raw_source": "2-3 cups/day"
}

Return only the JSON object, no prose.
"""


def parse_dose(
    raw_dose: Optional[str],
    food: Optional[str],
    llm_client,
) -> Optional[ParsedDose]:
    """Parse a free-text dose into a ``ParsedDose`` via the LLM.

    Returns ``None`` if ``raw_dose`` is empty or the LLM call fails.
    Callers treat a ``None`` / ``confidence == "not_a_dose"`` result as
    "skip F1 cleanly" — fail open, not closed.
    """
    if not raw_dose or not raw_dose.strip():
        return None
    messages = [
        {"role": "system", "content": DOSE_PARSE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"raw_dose: {raw_dose}\n"
                f"food: {food or 'unknown'}\n"
                f"Output:"
            ),
        },
    ]
    try:
        return llm_client.extract(messages, ParsedDose)
    except Exception:
        return None


def _norm_unit(unit: Optional[str]) -> str:
    return (unit or "").strip().lower().rstrip("s")


def normalize_to_reference_unit(
    parsed: ParsedDose, entry: ReferenceEntry
) -> Optional[float]:
    """Convert the parsed dose into the reference entry's unit.

    Returns ``None`` when the unit can't be matched — the F1 checker
    then skips, fail-open.
    """
    if parsed.numeric_value is None:
        return None
    value = float(parsed.numeric_value)
    parsed_unit = _norm_unit(parsed.unit)
    ref_unit = _norm_unit(entry.unit)
    if parsed_unit and parsed_unit == ref_unit:
        return value
    for alt in entry.alternate_units:
        alt_unit = _norm_unit(alt.get("unit"))
        ratio = alt.get("ratio")
        if parsed_unit and alt_unit == parsed_unit and ratio is not None:
            return value * float(ratio)
    # Bare number with no unit and reference unit is countable — accept
    # as the reference's own unit. This covers "100 per day" for apples.
    if not parsed_unit:
        return value
    return None


def check_dose_plausibility(
    food: Optional[str],
    parsed_dose: Optional[ParsedDose],
    reference_table: ReferenceTable,
) -> Optional[PlausibilityFailure]:
    """Compare a parsed dose against the reference thresholds.

    Returns a ``PlausibilityFailure`` when the dose meets or exceeds the
    harmful threshold (blocking) or the implausible threshold (warning).
    Returns ``None`` for any skip condition — missing food, dose not
    parseable, unit mismatch, food not in table.
    """
    if not food or parsed_dose is None:
        return None
    if parsed_dose.confidence == "not_a_dose":
        return None

    entry = reference_table.lookup(food)
    if entry is None:
        return None

    value = normalize_to_reference_unit(parsed_dose, entry)
    if value is None:
        return None

    typical_range = [entry.typical_daily_low, entry.typical_daily_high]

    if value >= entry.harmful_threshold:
        return PlausibilityFailure(
            failure_type="F1_dose",
            severity="blocking",
            reasoning=(
                f"The stated intake ({_fmt(value)} {entry.unit}) meets or "
                f"exceeds the documented harmful threshold "
                f"({_fmt(entry.harmful_threshold)} {entry.unit}) per "
                f"{entry.source}. At this level, harm is documented "
                f"regardless of the food's other properties."
            ),
            supporting_data={
                "stated_value": value,
                "unit": entry.unit,
                "harmful_threshold": entry.harmful_threshold,
                "implausibly_high": entry.implausibly_high,
                "typical_range": typical_range,
                "source": entry.source,
                "notes": entry.notes,
            },
        )

    if value >= entry.implausibly_high:
        return PlausibilityFailure(
            failure_type="F1_dose",
            severity="warning",
            reasoning=(
                f"The stated intake ({_fmt(value)} {entry.unit}) is far "
                f"above typical consumption "
                f"({_fmt(entry.typical_daily_low)}-"
                f"{_fmt(entry.typical_daily_high)} {entry.unit}). No "
                f"realistic population consumes at this level, so any "
                f"retrieved evidence will be on much smaller doses."
            ),
            supporting_data={
                "stated_value": value,
                "unit": entry.unit,
                "implausibly_high": entry.implausibly_high,
                "typical_range": typical_range,
                "source": entry.source,
            },
        )

    return None


def _fmt(x: float) -> str:
    """Render a float without a trailing ``.0`` for integer-valued doses."""
    if float(x).is_integer():
        return str(int(x))
    return f"{x:g}"
