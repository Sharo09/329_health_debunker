"""Adaptive (literature-informed) elicitation agent.

Replaces the static priority-table elicitor with one that **probes
PubMed before asking questions**. Implements the workflow described in
``docs/elicitation_spec.md`` (Approach 3):

    1. Resolve PICO concepts (LLM via ConceptResolver).
    2. Enumerate candidate evidence "slices" — combinations of axis
       values that materially change which papers PubMed will return.
    3. Probe each slice with ``pubmed.count()`` (cheap, ~200ms each).
    4. Rank slices by hit count.
    5. If the top/bottom ratio is high (>10×), the choice materially
       changes the evidence base — ask the user, with hit counts
       visible in the option text.
    6. If the ratio is low (<3×), pick the dominant slice silently.
    7. Optionally probe population variants on the chosen slice.
    8. Lock the PICO with the chosen overrides applied.

Budget caps: ``max_probes`` PubMed counts (default 15), ``max_questions``
user-facing questions (default 3). Both are hard caps.

The static ``ElicitationAgent`` in ``elicitor.py`` is unchanged — this
class is a sibling for the demo / API to opt into.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.elicitation.errors import (
    InsufficientElicitationError,
    UnscopableClaimError,
)
from src.elicitation.ui_adapter import UIAdapter
from src.retrieval.concept_resolver import ConceptResolver
from src.retrieval.pubmed_client import PubMedClient
from src.retrieval.query_builder import QueryBuilder
from src.retrieval.schemas import Concept
from src.schemas import LockedPICO, PartialPICO

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Probe data class
# ---------------------------------------------------------------------------

@dataclass
class ProbeSlice:
    """One candidate evidence slice — a slot-override combo + hit count."""

    label: str                          # human-readable, e.g. "Vitamin C for common cold"
    overrides: dict[str, str]           # PICO field overrides if user picks this
    query: str                          # the PubMed query the probe used
    axis: str                           # which axis the slice varies (outcome/component/etc.)
    count: int = 0                      # filled in by _run_probes
    notes: str = ""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AdaptiveElicitationAgent:
    """Literature-informed elicitation agent."""

    PROBE_BUDGET = 15
    MAX_QUESTIONS = 3
    HIGH_RATIO = 10.0           # top/bottom > this → ask user
    LOW_RATIO = 3.0             # top/bottom < this → don't ask, take dominant
    SUFFICIENT_HITS = 100       # top slice ≥ this → evidence is plentiful
    INSUFFICIENT_HITS = 5       # top slice < this → claim is genuinely understudied

    DEFAULT_POPULATION = "healthy_adults"
    DEFAULT_LOG_FILE = "logs/elicitation.jsonl"

    def __init__(
        self,
        ui_adapter: UIAdapter,
        pubmed: PubMedClient,
        resolver: ConceptResolver,
        log_file: Optional[str] = None,
        max_probes: int = PROBE_BUDGET,
        max_questions: int = MAX_QUESTIONS,
    ):
        self.ui = ui_adapter
        self.pubmed = pubmed
        self.resolver = resolver
        self.builder = QueryBuilder()
        self.log_file = log_file if log_file is not None else self.DEFAULT_LOG_FILE
        self.max_probes = max_probes
        self.max_questions = max_questions

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def elicit(self, partial: PartialPICO) -> LockedPICO:
        food = (partial.food or "").strip()
        if not food:
            raise UnscopableClaimError(
                "Claim cannot be scoped: no food identified by extraction."
            )

        concepts = self.resolver.resolve_pico(partial)

        slices = self._enumerate_slices(partial, concepts)
        probed = self._run_probes(slices)

        return self._decide_and_lock(partial, concepts, probed)

    # ------------------------------------------------------------------
    # Probe generation
    # ------------------------------------------------------------------

    def _enumerate_slices(
        self, partial: PartialPICO, concepts: dict[str, Concept]
    ) -> list[ProbeSlice]:
        food_c = concepts.get("food")
        outcome_c = concepts.get("outcome")
        component_c = concepts.get("component")

        slices: list[ProbeSlice] = []

        if food_c is None or outcome_c is None:
            # Can't probe without both axes — return empty so the caller
            # falls back to a sensible default.
            return slices

        # ---- Outcome variants (broader + sibling) via the resolver -------
        related_outcomes: list[Concept] = []
        for direction in ("broader", "sibling"):
            try:
                related = self.resolver.resolve_related(
                    "outcome", outcome_c, direction=direction
                )
                if related.mesh_terms or related.tiab_synonyms:
                    related_outcomes.append(related)
            except Exception as exc:
                logger.warning(
                    "resolve_related(outcome, %s) failed: %s", direction, exc
                )

        # ---- Slice 1: food + outcome (the literal claim) -----------------
        try:
            slices.append(
                ProbeSlice(
                    label=f"{food_c.user_term} for {outcome_c.user_term}",
                    overrides={},
                    query=self.builder.build_direct_query(
                        {"food": food_c, "outcome": outcome_c},
                        include_filters=False,
                    ),
                    axis="direct",
                )
            )
        except Exception as exc:
            logger.warning("direct slice failed: %s", exc)

        # ---- Slice 2: component + outcome (mechanism path) ---------------
        if component_c and (component_c.mesh_terms or component_c.tiab_synonyms):
            try:
                mech_q = self.builder.build_mechanism_query(
                    {"component": component_c, "outcome": outcome_c},
                    include_filters=False,
                )
                if mech_q:
                    slices.append(
                        ProbeSlice(
                            label=f"{component_c.user_term} for {outcome_c.user_term}",
                            overrides={"_use_component_focus": "true"},
                            query=mech_q,
                            axis="component",
                        )
                    )
            except Exception as exc:
                logger.warning("mechanism slice failed: %s", exc)

        # ---- Slices 3+: outcome variants × {food, component} -------------
        for related in related_outcomes:
            # food + related_outcome
            try:
                slices.append(
                    ProbeSlice(
                        label=f"{food_c.user_term} for {related.user_term}",
                        overrides={"outcome": related.user_term},
                        query=self.builder.build_related_outcome_query(
                            {"food": food_c, "outcome": outcome_c},
                            related_outcome=related,
                            include_filters=False,
                        ),
                        axis="outcome_swap",
                    )
                )
            except Exception as exc:
                logger.warning("food+related slice failed: %s", exc)

            # component + related_outcome
            if component_c and (component_c.mesh_terms or component_c.tiab_synonyms):
                try:
                    # Reuse build_direct_query, treating the component as the
                    # "food" axis and the related outcome as the outcome.
                    q = self.builder.build_direct_query(
                        {"food": component_c, "outcome": related},
                        include_filters=False,
                    )
                    slices.append(
                        ProbeSlice(
                            label=f"{component_c.user_term} for {related.user_term}",
                            overrides={
                                "_use_component_focus": "true",
                                "outcome": related.user_term,
                            },
                            query=q,
                            axis="component+outcome_swap",
                        )
                    )
                except Exception as exc:
                    logger.warning("component+related slice failed: %s", exc)

        return slices

    # ------------------------------------------------------------------
    # Probe execution
    # ------------------------------------------------------------------

    def _run_probes(self, slices: list[ProbeSlice]) -> list[ProbeSlice]:
        """Call ``pubmed.count`` for up to ``max_probes`` slices."""
        for s in slices[: self.max_probes]:
            try:
                s.count = int(self.pubmed.count(s.query))
            except Exception as exc:
                logger.warning("probe failed for %r: %s", s.label, exc)
                s.count = 0
                s.notes = f"probe error: {exc}"
        return slices[: self.max_probes]

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------

    def _decide_and_lock(
        self,
        partial: PartialPICO,
        concepts: dict[str, Concept],
        probed: list[ProbeSlice],
    ) -> LockedPICO:
        if not probed:
            # No probes ran. Lock with sensible defaults.
            return self._lock_with_overrides(partial, {}, [])

        ranked = sorted(probed, key=lambda s: s.count, reverse=True)
        top, bottom = ranked[0], ranked[-1]

        conversation: list[tuple[str, str]] = []
        chosen_overrides: dict[str, str] = {}
        questions_asked = 0

        # ---- Decision: ask about the evidence-landscape slice? -----------
        if (
            len(ranked) >= 2
            and questions_asked < self.max_questions
            and self._is_high_impact(ranked)
        ):
            top_n = ranked[: min(4, len(ranked))]
            display_label, overrides = self._ask_landscape(top_n)
            chosen_overrides = dict(overrides)
            conversation.append(
                (
                    self._landscape_question_text(top_n, ranked),
                    display_label,
                )
            )
            questions_asked += 1
        else:
            # Not informative enough to ask — silently take the top slice.
            chosen_overrides = dict(top.overrides)

        # ---- Optionally probe population on the chosen slice -------------
        population_asked = False
        if (
            questions_asked < self.max_questions
            and not partial.population
            # Only do population probing if we have probe budget left
            and len(probed) < self.max_probes
        ):
            pop_overrides, population_asked = self._maybe_probe_population(
                partial, concepts, chosen_overrides, conversation
            )
            if pop_overrides:
                chosen_overrides.update(pop_overrides)
                if population_asked:
                    questions_asked += 1

        # Slots that ended up set without the user being asked are
        # recorded as fallbacks in the audit trail.
        fallbacks: list[str] = []
        if not partial.population and not population_asked:
            fallbacks.append("population")

        return self._lock_with_overrides(
            partial, chosen_overrides, conversation, ranked, fallbacks
        )

    def _is_high_impact(self, ranked: list[ProbeSlice]) -> bool:
        """True iff top/bottom ratio > HIGH_RATIO and top has ≥ INSUFFICIENT_HITS."""
        top, bottom = ranked[0].count, ranked[-1].count
        if top < self.INSUFFICIENT_HITS:
            return False
        ratio = top / max(bottom, 1)
        return ratio >= self.HIGH_RATIO

    # ------------------------------------------------------------------
    # Question building
    # ------------------------------------------------------------------

    def _landscape_question_text(
        self, top_n: list[ProbeSlice], all_ranked: list[ProbeSlice]
    ) -> str:
        """Compose the natural-language preamble of the landscape question."""
        if not top_n:
            return "Which slice of evidence would you like to investigate?"
        top_label = top_n[0].label
        top_count = top_n[0].count
        if top_count >= 1000:
            strength = "the strongest evidence is"
        elif top_count >= 100:
            strength = "the most substantial evidence is"
        else:
            strength = "the most-studied option is"
        return (
            f"Based on what's actually published, {strength} on "
            f"\"{top_label}\" ({top_count:,} papers). The literal version of "
            "your claim has different evidence depth — pick the slice you'd "
            "like investigated."
        )

    def _ask_landscape(
        self, top_n: list[ProbeSlice]
    ) -> tuple[str, dict[str, str]]:
        """Render the landscape question and return (display_label, overrides)."""
        options: list[str] = []
        option_values: list[str] = []
        for s in top_n:
            options.append(f"{s.label} ({self._format_count(s.count)})")
            option_values.append(json.dumps(s.overrides))

        question = {
            "text": self._landscape_question_text(top_n, top_n),
            "options": options,
            "option_values": option_values,
            "allow_other": False,
        }
        display_label, internal_value = self.ui.ask(question)
        try:
            overrides = json.loads(internal_value) if internal_value else {}
            if not isinstance(overrides, dict):
                overrides = {}
        except (TypeError, ValueError):
            overrides = {}
        return display_label, overrides

    def _maybe_probe_population(
        self,
        partial: PartialPICO,
        concepts: dict[str, Concept],
        chosen_overrides: dict[str, str],
        conversation: list[tuple[str, str]],
    ) -> tuple[dict[str, str], bool]:
        """Probe population variants on the chosen slice; ask if it matters.

        Returns ``(overrides, asked_user)``. ``asked_user`` tells the
        caller whether the population was set via a real question vs.
        silently auto-picked, so it can mark the slot as a fallback
        in the audit log when appropriate.
        """
        # Default candidates — light hand-curated set that maps to real MeSH.
        candidates = [
            ("healthy_adults", "Adult"),
            ("children", "Child"),
            ("elderly", "Aged"),
            ("pregnant", "Pregnancy"),
        ]

        # Build base concepts for the chosen slice (post-override)
        food_c = concepts.get("food")
        outcome_label = chosen_overrides.get("outcome") or (
            partial.outcome or ""
        )
        outcome_c = concepts.get("outcome")
        if chosen_overrides.get("outcome"):
            # The chosen slice swapped outcome — re-resolve to get its MeSH.
            try:
                outcome_c = self.resolver.resolve(
                    "outcome", chosen_overrides["outcome"]
                )
            except Exception as exc:
                logger.warning("re-resolve outcome failed: %s", exc)

        if not food_c or not outcome_c:
            return {}, False

        # Build a probe per population
        results: list[tuple[str, int]] = []
        for token, mesh in candidates:
            try:
                pop_concept = Concept(
                    user_term=token,
                    mesh_terms=[mesh],
                    tiab_synonyms=[],
                    validated=True,
                )
                q = self.builder.build_direct_query(
                    {"food": food_c, "outcome": outcome_c, "population": pop_concept},
                    include_filters=False,
                )
                results.append((token, int(self.pubmed.count(q))))
            except Exception as exc:
                logger.warning("population probe %s failed: %s", token, exc)

        if not results:
            return {"population": self.DEFAULT_POPULATION}, False

        results.sort(key=lambda r: r[1], reverse=True)
        top, bottom = results[0][1], results[-1][1]
        # Only ask if it actually matters
        if top < self.INSUFFICIENT_HITS:
            return {"population": self.DEFAULT_POPULATION}, False
        if top / max(bottom, 1) < self.HIGH_RATIO:
            return {"population": results[0][0]}, False

        # Ratio is high → it matters → ask user.
        options = []
        option_values = []
        for token, count in results:
            options.append(
                f"{token.replace('_', ' ').title()} ({self._format_count(count)})"
            )
            option_values.append(token)

        question = {
            "text": (
                "Population also affects what evidence we'll find. Which group "
                "is your claim about?"
            ),
            "options": options,
            "option_values": option_values,
            "allow_other": True,
        }
        display_label, internal_value = self.ui.ask(question)
        conversation.append((question["text"], display_label))
        return {"population": internal_value or self.DEFAULT_POPULATION}, True

    # ------------------------------------------------------------------
    # PICO finalisation
    # ------------------------------------------------------------------

    def _lock_with_overrides(
        self,
        partial: PartialPICO,
        overrides: dict[str, str],
        conversation: list[tuple[str, str]],
        ranked: Optional[list[ProbeSlice]] = None,
        extra_fallbacks: Optional[list[str]] = None,
    ) -> LockedPICO:
        data = partial.model_dump()

        # Apply overrides to PICO fields. The "_use_component_focus" key is
        # metadata only — it doesn't touch a real slot, but downstream
        # retrieval may consult it via the locked PICO's notes field.
        if "outcome" in overrides:
            data["outcome"] = overrides["outcome"]
        if "population" in overrides:
            data["population"] = overrides["population"]

        fallbacks_used = list(data.get("fallbacks_used") or [])
        for f in (extra_fallbacks or []):
            if f not in fallbacks_used:
                fallbacks_used.append(f)

        if not data.get("population"):
            data["population"] = self.DEFAULT_POPULATION
            if "population" not in fallbacks_used:
                fallbacks_used.append("population")

        if not data.get("outcome"):
            raise InsufficientElicitationError(
                "outcome is required but was not supplied or chosen."
            )

        data["locked"] = True
        data["conversation"] = list(conversation or [])
        data["fallbacks_used"] = fallbacks_used

        locked = LockedPICO(**data)

        self._log(partial, locked, ranked or [], conversation, overrides)
        return locked

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_count(count: int) -> str:
        if count == 0:
            return "no papers found"
        if count < 10:
            return f"limited evidence, {count} papers"
        if count < 100:
            return f"some evidence, {count} papers"
        if count < 1000:
            return f"substantial evidence, {count} papers"
        return f"strong evidence, {count:,}+ papers"

    def _log(
        self,
        partial: PartialPICO,
        locked: LockedPICO,
        ranked: list[ProbeSlice],
        conversation: list[tuple[str, str]],
        overrides: dict[str, str],
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elicitation_mode": "adaptive",
            "raw_claim": partial.raw_claim,
            "input_partial_pico": partial.model_dump(),
            "probes": [
                {
                    "label": s.label,
                    "axis": s.axis,
                    "query": s.query,
                    "count": s.count,
                    "overrides": s.overrides,
                }
                for s in ranked
            ],
            "chosen_overrides": overrides,
            "conversation": [list(p) for p in (conversation or [])],
            "locked_pico": locked.model_dump(),
        }
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
