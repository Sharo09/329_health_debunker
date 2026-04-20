"""Station 1.5 orchestrator — combines F1 and F2/F3/F4 into one result.

Runs both checks for every PICO, collects failures, derives a
human-readable summary, and appends a JSONL audit record. The two
checks are independent on purpose: F1 is arithmetic, F2-F4 are LLM
judgment; running both keeps the output transparent and lets a single
pathological claim surface every failure mode that applies.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from src.extraction.llm_client import LLMClient
from src.plausibility.dose_checker import (
    check_dose_plausibility,
    check_generic_dose,
    parse_dose,
)
from src.plausibility.mechanism_checker import check_mechanism
from src.plausibility.reference_table import ReferenceTable
from src.plausibility.schemas import (
    ParsedDose,
    PlausibilityFailure,
    PlausibilityResult,
)
from src.schemas import PartialPICO

logger = logging.getLogger(__name__)

DEFAULT_LOG_FILE = "logs/plausibility.jsonl"

# Plausibility is latency-critical: it sits on the synchronous path
# between the user submitting a claim and seeing questions. The
# mechanism prompt has eight calibrated few-shots and the dose parser
# is a mechanical JSON extraction, so we run this on Flash rather
# than Pro. Keeps the gate under ~3 s instead of ~15 s.
_DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"
_DEFAULT_THINKING_BUDGET: int | None = None


class PlausibilityAgent:
    """Top-level Station 1.5 agent. Stateless between ``evaluate`` calls."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        reference_table: Optional[ReferenceTable] = None,
        log_file: Optional[str] = None,
    ):
        self.llm = (
            llm_client
            if llm_client is not None
            else LLMClient(
                model=_DEFAULT_MODEL,
                thinking_budget=_DEFAULT_THINKING_BUDGET,
            )
        )
        self.reference_table = (
            reference_table if reference_table is not None else ReferenceTable()
        )
        self.log_file = log_file if log_file is not None else DEFAULT_LOG_FILE

    def evaluate(self, pico: PartialPICO) -> PlausibilityResult:
        """Run F1 and F2/F3/F4 on a ``PartialPICO`` and return the result.

        The dose parse (F1 input) and the mechanism check (F2/F3/F4)
        are independent, so we fan them out in parallel. On typical
        claims this halves wall-clock latency from ~6 s to ~3 s. When
        the dose field is empty we skip the parse entirely and only
        the mechanism call goes out.
        """
        f234: list[PlausibilityFailure] = []
        parsed_dose: Optional[ParsedDose] = None
        f1: Optional[PlausibilityFailure] = None

        # Decide ahead of time whether to run the generic-dose LLM
        # fallback. When the food is in the reference table, the
        # deterministic check is authoritative and we skip the extra
        # call entirely. When it isn't, we start the fallback in
        # parallel with mechanism so plausibility latency stays at
        # ``max(mechanism, parse + generic)`` instead of the full
        # three-call chain.
        food_needs_fallback = bool(
            pico.food and self.reference_table.lookup(pico.food) is None
        )

        if pico.dose and pico.dose.strip():
            with ThreadPoolExecutor(max_workers=3) as pool:
                dose_future = pool.submit(self._parse_dose, pico)
                mech_future = pool.submit(self._run_mechanism, pico.raw_claim)

                if food_needs_fallback:
                    def _run_generic_dose():
                        pd = dose_future.result()
                        if pd is None:
                            return None
                        return check_generic_dose(pico.food, pd, self.llm)
                    generic_future = pool.submit(_run_generic_dose)
                else:
                    generic_future = None

                parsed_dose = dose_future.result()
                f234 = mech_future.result()
                generic_result = generic_future.result() if generic_future else None
        else:
            # Empty dose — parse and generic fallback are no-ops.
            f234 = self._run_mechanism(pico.raw_claim)
            generic_result = None

        # Deterministic arithmetic check runs unconditionally; it's
        # free once parsed_dose is in hand.
        deterministic = check_dose_plausibility(
            pico.food, parsed_dose, self.reference_table
        )
        # Prefer the deterministic result when it fired. Fall back to
        # the LLM-judged generic result for foods not in the table.
        f1 = deterministic or generic_result

        failures: list[PlausibilityFailure] = []
        if f1 is not None:
            failures.append(f1)
        failures.extend(f234)

        warnings = [f.reasoning for f in failures if f.severity == "warning"]
        # ``should_proceed_to_pipeline`` is derived by the model validator
        # on ``PlausibilityResult``; we don't set it explicitly.
        result = PlausibilityResult(
            failures=failures,
            warnings=warnings,
            reasoning_summary="",
            dose_parse=parsed_dose,
        )
        result.reasoning_summary = self._summarise(
            failures, result.should_proceed_to_pipeline
        )

        self._log(pico, result)
        return result

    def _parse_dose(self, pico: PartialPICO) -> Optional[ParsedDose]:
        return parse_dose(pico.dose, pico.food, self.llm)

    def _run_mechanism(self, raw_claim: str) -> list[PlausibilityFailure]:
        """Wrap the mechanism check with fail-open behaviour.

        Kept as a method so both the parallel and serial paths share the
        same exception handling.
        """
        try:
            return check_mechanism(raw_claim, self.llm)
        except Exception as exc:
            logger.warning("Mechanism check failed, failing open: %s", exc)
            return []

    def _summarise(
        self,
        failures: list[PlausibilityFailure],
        should_proceed: bool,
    ) -> str:
        if not failures:
            return (
                "Claim is worth investigating empirically. "
                "Proceeding to elicitation and retrieval."
            )
        parts = [f"{f.failure_type} ({f.severity}): {f.reasoning}" for f in failures]
        prefix = (
            "Plausibility issues detected - pipeline halted. "
            if not should_proceed
            else "Plausibility warnings - proceeding with caveats. "
        )
        return prefix + " ".join(parts)

    def _log(self, pico: PartialPICO, result: PlausibilityResult) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_claim": pico.raw_claim,
            "pico": pico.model_dump(),
            "result": result.model_dump(),
        }
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
