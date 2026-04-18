"""PICO schemas shared across stations.

Station 1 (extraction) produces a `PartialPICO`; Station 2 (elicitation)
locks it into a `LockedPICO`; Station 3 (retrieval) consumes the locked
form.
"""

from typing import Optional

from pydantic import BaseModel, Field


class PartialPICO(BaseModel):
    raw_claim: str
    food: Optional[str] = None
    form: Optional[str] = None
    dose: Optional[str] = None
    frequency: Optional[str] = None
    population: Optional[str] = None
    component: Optional[str] = None
    outcome: Optional[str] = None
    ambiguous_slots: list[str] = Field(default_factory=list)


class LockedPICO(PartialPICO):
    locked: bool = True
    conversation: list[tuple[str, str]] = Field(default_factory=list)
    fallbacks_used: list[str] = Field(default_factory=list)
