"""The Station 2 elicitation agent.

Takes a `PartialPICO` from Station 1, asks up to `MAX_QUESTIONS`
clarifying questions via the provided `UIAdapter`, and returns a
`LockedPICO` with all required slots filled. Every call appends an
audit record to `logs/elicitation.jsonl`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from src.elicitation.errors import (
    InsufficientElicitationError,
    UnscopableClaimError,
)
from src.elicitation.priority_table import get_priority
from src.elicitation.question_templates import FALLBACK_VALUE, get_question
from src.elicitation.ui_adapter import UIAdapter
from src.schemas import LockedPICO, PartialPICO

logger = logging.getLogger(__name__)


class ElicitationAgent:
    MAX_QUESTIONS = 3
    DEFAULT_LOG_FILE = "logs/elicitation.jsonl"
    DEFAULT_POPULATION = "healthy_adults"

    def __init__(self, ui_adapter: UIAdapter, log_file: Optional[str] = None):
        self.ui = ui_adapter
        self.log_file = log_file if log_file is not None else self.DEFAULT_LOG_FILE

    def elicit(self, partial: PartialPICO) -> LockedPICO:
        food = _normalize_food(partial.food)
        if not food:
            raise UnscopableClaimError(
                "Claim cannot be scoped: no food identified by extraction."
            )

        compound_warning = None
        if _is_compound(food):
            first = _first_food(food)
            compound_warning = (
                f"Compound food detected ({food!r}); proceeding with {first!r}. "
                "Multi-food claims are not yet supported."
            )
            logger.warning(compound_warning)
            food = first

        working = partial.model_copy(update={"food": food})

        slots_to_ask = self.select_slots_to_ask(working)

        conversation: list[tuple[str, str]] = []
        fallbacks_used: list[str] = []
        new_values: dict[str, str] = {}
        other_slots: list[str] = []

        for slot in slots_to_ask:
            template = get_question(slot, food)
            display_label, internal_value = self.ui.ask(dict(template))
            conversation.append((template["text"], display_label))

            if internal_value == FALLBACK_VALUE:
                new_values[slot] = FALLBACK_VALUE
                fallbacks_used.append(slot)
                continue

            if internal_value not in template["option_values"]:
                logger.warning(
                    "Free-text answer for slot=%r (food=%r); downstream "
                    "query construction may be degraded.",
                    slot,
                    food,
                )
                other_slots.append(slot)

            new_values[slot] = internal_value

        population_val = new_values.get("population", working.population)
        if population_val is None:
            new_values["population"] = self.DEFAULT_POPULATION
            fallbacks_used.append("population")

        outcome_val = new_values.get("outcome", working.outcome)
        if outcome_val is None:
            raise InsufficientElicitationError(
                "Cannot lock PICO: outcome is required but was not supplied, "
                "not flagged as ambiguous, and therefore was never asked."
            )

        locked = self._build_locked(working, new_values, conversation, fallbacks_used)

        self._log_record(
            partial=partial,
            working=working,
            slots_asked=slots_to_ask,
            conversation=conversation,
            fallbacks_used=fallbacks_used,
            locked=locked,
            compound_warning=compound_warning,
            other_slots=other_slots,
        )

        return locked

    def select_slots_to_ask(self, partial: PartialPICO) -> list[str]:
        priority = get_priority(partial.food)
        chosen: list[str] = []
        for slot in priority:
            if len(chosen) >= self.MAX_QUESTIONS:
                break
            if slot not in partial.ambiguous_slots:
                continue
            if getattr(partial, slot, None) is not None:
                continue
            chosen.append(slot)
        return chosen

    def _build_locked(
        self,
        partial: PartialPICO,
        new_values: dict[str, str],
        conversation: list[tuple[str, str]],
        fallbacks_used: list[str],
    ) -> LockedPICO:
        data = partial.model_dump()
        for slot, value in new_values.items():
            data[slot] = value
        data.update(
            locked=True,
            conversation=conversation,
            fallbacks_used=fallbacks_used,
        )
        return LockedPICO(**data)

    def _log_record(
        self,
        partial: PartialPICO,
        working: PartialPICO,
        slots_asked: list[str],
        conversation: list[tuple[str, str]],
        fallbacks_used: list[str],
        locked: LockedPICO,
        compound_warning: Optional[str],
        other_slots: list[str],
    ) -> None:
        record: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_claim": partial.raw_claim,
            "input_partial_pico": partial.model_dump(),
            "slots_asked": list(slots_asked),
            "conversation": [list(pair) for pair in conversation],
            "locked_pico": locked.model_dump(),
            "fallbacks_used": list(fallbacks_used),
        }
        if compound_warning:
            record["compound_warning"] = compound_warning
        if other_slots:
            record["other_slots"] = list(other_slots)

        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


def _normalize_food(food: Optional[str]) -> Optional[str]:
    if food is None:
        return None
    stripped = food.strip()
    return stripped or None


_COMPOUND_SEP_RE = re.compile(r"\s+and\s+|\s+or\s+|,|/", flags=re.IGNORECASE)


def _is_compound(food: str) -> bool:
    return bool(_COMPOUND_SEP_RE.search(food))


def _first_food(food: str) -> str:
    for chunk in _COMPOUND_SEP_RE.split(food):
        chunk = chunk.strip()
        if chunk:
            return chunk
    return food.strip()
