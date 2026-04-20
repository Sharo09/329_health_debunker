"""Curated quantitative reference data for F1 dose checks.

``ReferenceTable`` loads ``data/plausibility_reference.yaml`` and exposes
case-insensitive lookups keyed by canonical food name. Missing foods
return ``None`` — the F1 checker treats "not in table" as "skip F1,
fail open" so false blocks stay rare.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


_DEFAULT_REFERENCE_PATH = Path(__file__).resolve().parents[2] / "data" / "plausibility_reference.yaml"


class ReferenceEntry(BaseModel):
    """One food/nutrient row in the plausibility reference table."""

    canonical_name: str
    unit: str
    typical_daily_low: float
    typical_daily_high: float
    implausibly_high: float
    harmful_threshold: float
    source: str
    notes: str = ""
    alternate_units: list[dict] = Field(default_factory=list)


class ReferenceTable:
    """Loader for the plausibility reference YAML.

    Instantiate once at agent startup. ``lookup`` is case-insensitive and
    whitespace-tolerant and returns ``None`` for foods not in the table.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else _DEFAULT_REFERENCE_PATH
        self._entries: dict[str, ReferenceEntry] = self._load()

    def _load(self) -> dict[str, ReferenceEntry]:
        raw = yaml.safe_load(self.path.read_text()) or {}
        out: dict[str, ReferenceEntry] = {}
        for name, body in raw.items():
            entry = ReferenceEntry(canonical_name=name, **body)
            out[name.strip().lower()] = entry
        return out

    def lookup(self, food: Optional[str]) -> Optional[ReferenceEntry]:
        if not food:
            return None
        base = food.strip().lower()
        # Try each candidate in descending specificity. Station 1
        # extracts food terms as written in the claim ("apples",
        # "eggs", "red meat"), so we normalise case, spaces, and
        # trailing plural 's' before giving up.
        candidates = [
            base.replace(" ", "_"),
            base,
            base.rstrip("s").replace(" ", "_"),
            base.rstrip("s"),
        ]
        for key in candidates:
            if key in self._entries:
                return self._entries[key]
        return None

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, food: str) -> bool:
        return self.lookup(food) is not None
