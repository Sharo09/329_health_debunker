"""Schemas for Station 1 (extraction).

The rich ``PartialPICO`` wraps each PICO slot in a ``SlotExtraction`` so
downstream stages can reason about confidence (explicit / implied /
absent) rather than collapsing to ``Optional[str]``. Station 2 consumes
the flat shape — ``FlatPartialPICO`` is an alias of
``src.schemas.PartialPICO`` to guarantee the two sides never drift.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from src.schemas import PartialPICO as FlatPartialPICO  # noqa: F401 — re-exported

SlotConfidence = Literal["explicit", "implied", "absent"]

SLOT_NAMES: tuple[str, ...] = (
    "food",
    "form",
    "dose",
    "frequency",
    "population",
    "component",
    "outcome",
)

# Values that are nominally non-null but too vague to act on. A slot with
# one of these values is treated as ambiguous alongside ``absent`` slots.
VAGUE_VALUES: set[str] = {
    "some",
    "a lot",
    "a little",
    "sometimes",
    "often",
    "frequently",
    "occasionally",
    "any",
    "any amount",
}


class SlotExtraction(BaseModel):
    value: Optional[str] = None
    confidence: SlotConfidence = "absent"
    source_span: Optional[str] = None

    @model_validator(mode="after")
    def _check_confidence_invariants(self) -> "SlotExtraction":
        if self.confidence == "explicit":
            if self.value is None:
                raise ValueError(
                    "SlotExtraction with confidence='explicit' must have a non-null value."
                )
            if self.source_span is None:
                raise ValueError(
                    "SlotExtraction with confidence='explicit' must have a non-null source_span."
                )
        elif self.confidence == "absent":
            if self.value is not None:
                raise ValueError(
                    "SlotExtraction with confidence='absent' must have value=None."
                )
        return self


def _empty_slot() -> SlotExtraction:
    return SlotExtraction()


class PartialPICO(BaseModel):
    raw_claim: str

    food: SlotExtraction = Field(default_factory=_empty_slot)
    form: SlotExtraction = Field(default_factory=_empty_slot)
    dose: SlotExtraction = Field(default_factory=_empty_slot)
    frequency: SlotExtraction = Field(default_factory=_empty_slot)
    population: SlotExtraction = Field(default_factory=_empty_slot)
    component: SlotExtraction = Field(default_factory=_empty_slot)
    outcome: SlotExtraction = Field(default_factory=_empty_slot)

    # Computed deterministically from the SlotExtractions; any caller-
    # supplied value is overridden on construction.
    ambiguous_slots: list[str] = Field(default_factory=list)

    # Scope gate.
    is_food_claim: bool = True
    scope_rejection_reason: Optional[str] = None

    # Set when the claim contains multiple sub-claims and we kept only
    # the primary one (per the MVP non-goal on decomposition).
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _recompute_ambiguous_slots(self) -> "PartialPICO":
        self.ambiguous_slots = compute_ambiguous_slots(self)
        return self

    def to_flat(self) -> FlatPartialPICO:
        """Return the flat shape consumed by Station 2."""
        return FlatPartialPICO(
            raw_claim=self.raw_claim,
            food=self.food.value,
            form=self.form.value,
            dose=self.dose.value,
            frequency=self.frequency.value,
            population=self.population.value,
            component=self.component.value,
            outcome=self.outcome.value,
            ambiguous_slots=list(self.ambiguous_slots),
        )


def compute_ambiguous_slots(pico: "PartialPICO") -> list[str]:
    """Deterministic recomputation of ``ambiguous_slots``.

    A slot is ambiguous if:
      - its confidence is ``"absent"``, OR
      - its value (case-insensitive, trimmed) is in ``VAGUE_VALUES``.
    """
    ambiguous: list[str] = []
    for slot_name in SLOT_NAMES:
        slot: SlotExtraction = getattr(pico, slot_name)
        if slot.confidence == "absent":
            ambiguous.append(slot_name)
        elif slot.value is not None and slot.value.strip().lower() in VAGUE_VALUES:
            ambiguous.append(slot_name)
    return ambiguous
