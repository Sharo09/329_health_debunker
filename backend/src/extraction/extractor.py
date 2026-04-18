"""The Station 1 claim extractor.

Takes a raw user claim, calls the LLM to extract a ``PartialPICO``,
then post-processes:
  - normalizes the food name against the curated demo list,
  - recomputes ``ambiguous_slots`` deterministically,
  - ensures scope-rejected claims are returned with empty slots.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from backend.src.extraction.errors import EmptyClaimError
from backend.src.extraction.food_normalizer import normalize_food
from backend.src.extraction.llm_client import LLMClient
from backend.src.extraction.prompt import build_extraction_prompt
from backend.src.extraction.schemas import (
    SLOT_NAMES,
    PartialPICO,
    SlotExtraction,
    compute_ambiguous_slots,
)

logger = logging.getLogger(__name__)


class ClaimExtractor:
    DEFAULT_LOG_FILE = "logs/extraction.jsonl"
    MAX_CLAIM_LEN = 500

    def __init__(self, llm_client: LLMClient, log_file: Optional[str] = None):
        self.llm = llm_client
        self.log_file = log_file if log_file is not None else self.DEFAULT_LOG_FILE

    def extract(self, raw_claim: str) -> PartialPICO:
        if not raw_claim or not raw_claim.strip():
            raise EmptyClaimError("Claim is empty or whitespace-only.")

        truncated = False
        original_length = len(raw_claim)
        if original_length > self.MAX_CLAIM_LEN:
            logger.warning(
                "Claim truncated from %d to %d chars.",
                original_length,
                self.MAX_CLAIM_LEN,
            )
            raw_claim = raw_claim[: self.MAX_CLAIM_LEN]
            truncated = True

        messages = build_extraction_prompt(raw_claim)
        pico: PartialPICO = self.llm.extract(messages, PartialPICO)  # type: ignore[assignment]

        food_normalization = None
        if pico.is_food_claim:
            food_normalization = self._normalize_food_slot(pico)
        else:
            self._force_scope_rejection_shape(pico)

        # Never trust the LLM's ambiguous_slots; recompute from the truth.
        pico.ambiguous_slots = compute_ambiguous_slots(pico)

        self._log(
            raw_claim=raw_claim,
            original_length=original_length,
            truncated=truncated,
            pico=pico,
            food_normalization=food_normalization,
        )

        return pico

    def _normalize_food_slot(self, pico: PartialPICO) -> Optional[dict]:
        """If the food name normalizes to a different canonical, rewrite it.

        ``source_span`` is left untouched — it already carries the verbatim
        claim substring the LLM pulled from, which is the "original" per
        the post-processing spec. Returns a dict describing the rewrite
        for the audit log, or ``None`` if no rewrite happened.
        """
        if pico.food.value is None:
            return None

        canonical, _is_known = normalize_food(pico.food.value)
        if not canonical or canonical == pico.food.value:
            return None

        original_value = pico.food.value
        pico.food.value = canonical
        return {"from": original_value, "to": canonical}

    def _force_scope_rejection_shape(self, pico: PartialPICO) -> None:
        """Belt-and-braces: scope-rejected claims must have empty slots.

        The prompt already instructs the LLM to emit absent slots in
        this case; this enforces it in case the LLM wobbles.
        """
        if pico.scope_rejection_reason is None:
            pico.scope_rejection_reason = "Claim is not a food or nutrition claim."
        for slot_name in SLOT_NAMES:
            current = getattr(pico, slot_name)
            if current.confidence != "absent" or current.value is not None:
                setattr(pico, slot_name, SlotExtraction())

    def _log(
        self,
        raw_claim: str,
        original_length: int,
        truncated: bool,
        pico: PartialPICO,
        food_normalization: Optional[dict],
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_claim": raw_claim,
            "original_length": original_length,
            "truncated": truncated,
            "pico": pico.model_dump(),
            "food_normalization": food_normalization,
        }
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
