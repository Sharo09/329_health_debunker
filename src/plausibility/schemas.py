"""Schemas for Station 1.5 — Plausibility.

The plausibility stage sits between extraction (Station 1) and elicitation
(Station 2). It decides whether a claim is worth investigating empirically
before the full retrieval pipeline spends time on it. It does NOT produce
a verdict; it produces a gate.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

FailureType = Literal[
    "F1_dose",
    "F2_feasibility",
    "F3_mechanism",
    "F4_frame",
]

Severity = Literal["blocking", "warning"]

DoseConfidence = Literal["high", "medium", "low", "not_a_dose"]


class ParsedDose(BaseModel):
    """Structured representation of the claim's stated dose.

    Produced by the dose parser (LLM-assisted) when the PICO has a
    non-empty ``dose`` field. Echoed into the final ``PlausibilityResult``
    for audit even when no F1 failure fires.
    """

    numeric_value: Optional[float] = None
    unit: Optional[str] = None            # e.g. "apple", "IU", "mg", "liter"
    time_basis: Optional[str] = None      # "per day" / "per week" / "total" / None
    confidence: DoseConfidence = "not_a_dose"
    raw_source: str = ""


class PlausibilityFailure(BaseModel):
    """One specific plausibility concern against a claim."""

    failure_type: FailureType
    severity: Severity
    reasoning: str                        # 1–3 sentence user-facing explanation
    supporting_data: dict = Field(default_factory=dict)


class PlausibilityResult(BaseModel):
    """Full output of the plausibility stage.

    ``should_proceed_to_pipeline`` is computed from the failures list
    and cannot be set inconsistently — the validator derives it. The
    rule: proceed iff no failure has ``severity == "blocking"``.
    """

    should_proceed_to_pipeline: bool = True
    failures: list[PlausibilityFailure] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    dose_parse: Optional[ParsedDose] = None

    @model_validator(mode="after")
    def _derive_should_proceed(self) -> "PlausibilityResult":
        """Force ``should_proceed_to_pipeline`` to match the failures list.

        If any failure is blocking → False, else True. This prevents
        callers from constructing inconsistent results (e.g.
        should_proceed=True while a blocking failure is present).
        """
        blocks = any(f.severity == "blocking" for f in self.failures)
        # Pydantic v2: direct assignment is fine because model_config defaults
        # allow mutation during validation.
        self.should_proceed_to_pipeline = not blocks
        return self
