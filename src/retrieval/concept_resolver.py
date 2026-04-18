"""Concept resolver — translates everyday PICO slot values into PubMed MeSH.

This is the critical fix for the orange/flu failure. Instead of asking
PubMed for ``"orange"[MeSH Terms]`` (which is the *colour*) and
``"flu"[MeSH Terms]`` (which doesn't exist), we:

1. Ask an LLM to propose the real MeSH Heading for the user's term,
   considering the slot type (food / outcome / component / population)
   and the surrounding PICO as disambiguation context.
2. Validate each proposed MeSH against PubMed via a cheap count call —
   if the MeSH term returns fewer than ``VALIDATION_THRESHOLD`` hits,
   it's not a real productive MeSH Heading and we fall through to the
   next candidate.
3. Return a ``Concept`` carrying the validated MeSH terms plus free-text
   ``tiab_synonyms`` the query builder can mix in.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from pydantic import BaseModel, Field

from src.extraction.llm_client import LLMClient
from src.retrieval.pubmed_client import PubMedClient
from src.retrieval.schemas import Concept
from src.schemas import PartialPICO

logger = logging.getLogger(__name__)

VALIDATION_THRESHOLD = 100  # hits under this → probably not a real productive MeSH
_MAX_VALIDATIONS = 4        # hard cap on MeSH validation calls per slot
_RELATED_OVERLAP_CAP = 0.5  # >= this overlap with original → tautology, reject

# Slots that actually get resolved. "form" / "dose" / "frequency" are used
# as filters, not as MeSH concepts, so we don't ask the LLM about them.
_RESOLVABLE_SLOTS: tuple[str, ...] = ("food", "outcome", "component", "population")


# ---------------------------------------------------------------------------
# LLM response schema
# ---------------------------------------------------------------------------

class _LLMResolution(BaseModel):
    """What we ask the LLM to return for one concept-resolution call."""

    primary_mesh: str = Field(
        ...,
        description="The best real MeSH Heading for the user term in context.",
    )
    alternative_mesh: list[str] = Field(
        default_factory=list,
        description="Fallback MeSH Headings, tried in order if primary fails validation.",
    )
    tiab_synonyms: list[str] = Field(
        default_factory=list,
        description="Free-text synonyms for [tiab] search alongside MeSH.",
    )
    reasoning: str = Field(
        default="",
        description="1-2 sentences explaining the mapping and disambiguation.",
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a medical information retrieval specialist. Your job is to
translate an everyday term from a health claim into PubMed's controlled
vocabulary (MeSH — Medical Subject Headings) plus useful free-text
synonyms.

For each user term you receive, you will also know:
  - its SLOT TYPE ("food", "outcome", "component", or "population")
  - CONTEXT — the other slot values from the same claim, for disambiguation.

Return a JSON object with four fields:
  primary_mesh      A real MeSH Heading. Must be an actual MeSH Heading,
                    not free text. If uncertain, put it in alternative_mesh
                    instead and leave primary_mesh as the closest real one.
  alternative_mesh  Fallback MeSH Headings, most specific first.
  tiab_synonyms     Free-text synonyms (for title/abstract search).
  reasoning         1-2 sentences explaining the choice and any disambiguation.

CRITICAL RULES:
  1. Pick the MeSH Heading appropriate for the SLOT TYPE. "Orange" in a food
     claim is the fruit (Citrus sinensis), NOT the colour.
  2. Prefer specific MeSH over general. "flu" → "Influenza, Human", not "Infection".
  3. Include at least 2 tiab_synonyms (singular, plural, colloquial, scientific).
  4. If the user term has no direct MeSH equivalent, return the closest MeSH
     Heading and note the mismatch in reasoning.

EXAMPLES

--- food ---
Input:  user_term="orange", slot="food", context={"outcome": "flu"}
Output: {
  "primary_mesh": "Citrus sinensis",
  "alternative_mesh": ["Citrus"],
  "tiab_synonyms": ["orange", "oranges", "sweet orange", "citrus fruit"],
  "reasoning": "In a food claim, 'orange' is the fruit (Citrus sinensis). 'Orange' as a standalone MeSH term refers to the colour and is irrelevant."
}

Input:  user_term="turmeric", slot="food", context={"outcome": "inflammation"}
Output: {
  "primary_mesh": "Curcuma",
  "alternative_mesh": ["Curcumin"],
  "tiab_synonyms": ["turmeric", "curcuma longa", "curcumin"],
  "reasoning": "Turmeric is the spice from Curcuma longa; Curcumin is the active compound (separate MeSH)."
}

Input:  user_term="red meat", slot="food", context={"outcome": "cancer"}
Output: {
  "primary_mesh": "Red Meat",
  "alternative_mesh": ["Meat"],
  "tiab_synonyms": ["red meat", "beef", "pork", "lamb"],
  "reasoning": "Red Meat is a real MeSH Heading as of 2016."
}

--- outcome ---
Input:  user_term="flu", slot="outcome", context={"food": "orange"}
Output: {
  "primary_mesh": "Influenza, Human",
  "alternative_mesh": ["Orthomyxoviridae Infections"],
  "tiab_synonyms": ["influenza", "flu", "seasonal flu"],
  "reasoning": "'Flu' is not a MeSH term. The correct Heading is 'Influenza, Human'."
}

Input:  user_term="miscarriage", slot="outcome", context={"food": "coffee"}
Output: {
  "primary_mesh": "Abortion, Spontaneous",
  "alternative_mesh": ["Pregnancy Complications"],
  "tiab_synonyms": ["miscarriage", "spontaneous abortion", "pregnancy loss"],
  "reasoning": "'Miscarriage' in MeSH is 'Abortion, Spontaneous'."
}

Input:  user_term="cancer", slot="outcome", context={"food": "red meat"}
Output: {
  "primary_mesh": "Neoplasms",
  "alternative_mesh": ["Colorectal Neoplasms"],
  "tiab_synonyms": ["cancer", "neoplasm", "malignancy", "tumor"],
  "reasoning": "'Cancer' maps to 'Neoplasms' in MeSH. Include 'Colorectal Neoplasms' as the likely specific category given the red-meat context."
}

--- component ---
Input:  user_term="vitamin C", slot="component", context={"food": "orange", "outcome": "flu"}
Output: {
  "primary_mesh": "Ascorbic Acid",
  "alternative_mesh": [],
  "tiab_synonyms": ["vitamin C", "ascorbic acid", "ascorbate"],
  "reasoning": "MeSH Heading for vitamin C is 'Ascorbic Acid'."
}

Input:  user_term="caffeine", slot="component", context={"food": "coffee"}
Output: {
  "primary_mesh": "Caffeine",
  "alternative_mesh": [],
  "tiab_synonyms": ["caffeine"],
  "reasoning": "Caffeine is a MeSH Heading."
}

--- population ---
Input:  user_term="pregnant women", slot="population", context={"food": "alcohol"}
Output: {
  "primary_mesh": "Pregnancy",
  "alternative_mesh": ["Pregnant Women"],
  "tiab_synonyms": ["pregnant women", "pregnancy", "during pregnancy"],
  "reasoning": "'Pregnancy' is the MeSH for the state; 'Pregnant Women' is the Heading for the population and should be preferred when available."
}

Input:  user_term="children", slot="population", context={"food": "milk"}
Output: {
  "primary_mesh": "Child",
  "alternative_mesh": ["Adolescent", "Child, Preschool"],
  "tiab_synonyms": ["children", "pediatric", "school-age"],
  "reasoning": "'Child' is the general MeSH; Adolescent / Child, Preschool are more specific if the age band is known."
}

Return only the JSON object, no prose around it.
"""


# ---------------------------------------------------------------------------
# Related-concept system prompt (used by resolve_related)
# ---------------------------------------------------------------------------

_DIRECTION_HINTS: dict[str, str] = {
    "broader": "a more general PARENT concept that subsumes the original",
    "mechanism": "the underlying biological mechanism or causal process",
    "sibling": "a closely related SIBLING concept — same semantic space, different disease/condition",
    "related": "a closely related but NON-IDENTICAL concept",
}


_RELATED_SYSTEM_PROMPT = """\
You produce a related-but-DIFFERENT MeSH Heading from a starting one,
for the purpose of semantic query relaxation on PubMed.

HARD RULE
---------
The primary_mesh you return MUST NOT be identical to any MeSH Heading
in the input. You are bridging to adjacent literature, not re-affirming
the starting term. A result that matches the input MeSH is a FAILURE.

Directions
----------
  broader   — a parent concept subsuming the input
              (Influenza, Human → Respiratory Tract Infections)
  mechanism — the underlying biological mechanism
              (Influenza, Human → Immunity, Innate; Obesity → Insulin Resistance)
  sibling   — a neighbouring condition in the same space
              (Influenza, Human → Common Cold; Common Cold → Pharyngitis)
  related   — any closely related but non-identical concept

EXAMPLES

Input: slot=outcome, original="Influenza, Human", direction=sibling
Output: {
  "primary_mesh": "Common Cold",
  "alternative_mesh": ["Respiratory Tract Infections", "Rhinovirus"],
  "tiab_synonyms": ["common cold", "rhinovirus", "upper respiratory infection"],
  "reasoning": "Common Cold is a neighbouring MeSH in the respiratory-infection space."
}

Input: slot=outcome, original="Influenza, Human", direction=broader
Output: {
  "primary_mesh": "Respiratory Tract Infections",
  "alternative_mesh": ["Virus Diseases", "Orthomyxoviridae Infections"],
  "tiab_synonyms": ["respiratory tract infection", "respiratory infection"],
  "reasoning": "Respiratory Tract Infections is the parent MeSH category."
}

Input: slot=outcome, original="Myocardial Infarction", direction=broader
Output: {
  "primary_mesh": "Cardiovascular Diseases",
  "alternative_mesh": ["Coronary Artery Disease", "Ischemic Heart Disease"],
  "tiab_synonyms": ["cardiovascular disease", "CVD", "heart disease"],
  "reasoning": "Cardiovascular Diseases subsumes MI."
}

Input: slot=outcome, original="Type 2 Diabetes", direction=mechanism
Output: {
  "primary_mesh": "Insulin Resistance",
  "alternative_mesh": ["Blood Glucose", "Hyperglycemia"],
  "tiab_synonyms": ["insulin resistance", "glucose metabolism"],
  "reasoning": "Insulin resistance is the core mechanism of T2D."
}

Return the same JSON shape as the main resolver (primary_mesh,
alternative_mesh, tiab_synonyms, reasoning). No prose around it.
"""


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class ConceptResolver:
    """LLM-based MeSH resolution with PubMed hit-count validation."""

    def __init__(
        self,
        llm_client: LLMClient,
        pubmed_client: PubMedClient,
        validation_threshold: int = VALIDATION_THRESHOLD,
        max_workers: int = 4,
    ):
        """Resolve up to ``max_workers`` PICO slots in parallel.

        Drop to ``max_workers=1`` only if you're running against a
        tightly rate-limited LLM tier (e.g., Gemini free tier at 5
        req/min — parallel bursts trip it instantly).
        """
        self.llm = llm_client
        self.pubmed = pubmed_client
        self.threshold = validation_threshold
        self.max_workers = max(1, max_workers)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        slot_name: str,
        user_term: str,
        context: Optional[dict] = None,
    ) -> Concept:
        """Translate one user term into a validated ``Concept``."""
        user_term = (user_term or "").strip()
        if not user_term:
            return Concept(
                user_term=user_term,
                mesh_terms=[],
                tiab_synonyms=[],
                validated=False,
                notes="empty user term",
            )

        proposal = self._call_llm(slot_name, user_term, context or {})

        # Try primary_mesh, then each alternative_mesh, until we've validated
        # a few. Cap validation calls at ``_MAX_VALIDATIONS`` so a chatty LLM
        # can't balloon our PubMed budget.
        candidates: list[str] = []
        if proposal.primary_mesh:
            candidates.append(proposal.primary_mesh)
        candidates.extend(proposal.alternative_mesh or [])

        validated_mesh: list[str] = []
        best_effort: Optional[str] = None
        validation_notes: list[str] = []
        for mesh in candidates[:_MAX_VALIDATIONS]:
            if not mesh.strip():
                continue
            if self._validate_mesh(mesh):
                validated_mesh.append(mesh)
            else:
                validation_notes.append(f"{mesh!r} below threshold")
                if best_effort is None:
                    best_effort = mesh

        if validated_mesh:
            final_mesh = validated_mesh
            validated_flag = True
        elif best_effort is not None:
            # Keep the LLM's best guess so we're not empty-handed; downstream
            # can still fall back to tiab synonyms via validated_flag=False.
            final_mesh = [best_effort]
            validated_flag = False
        else:
            final_mesh = []
            validated_flag = False

        # Dedupe synonyms, preserve order.
        synonyms: list[str] = []
        seen: set[str] = set()
        for syn in proposal.tiab_synonyms or []:
            s = syn.strip()
            if s and s.lower() not in seen:
                synonyms.append(s)
                seen.add(s.lower())
        # Ensure the user term itself is searchable as free text.
        if user_term.lower() not in seen:
            synonyms.append(user_term)

        notes_parts: list[str] = []
        if proposal.reasoning:
            notes_parts.append(proposal.reasoning)
        if validation_notes:
            notes_parts.append("; ".join(validation_notes))

        return Concept(
            user_term=user_term,
            mesh_terms=final_mesh,
            tiab_synonyms=synonyms,
            validated=validated_flag,
            notes="\n".join(notes_parts) if notes_parts else None,
        )

    def resolve_related(
        self,
        slot_name: str,
        original: Concept,
        direction: str = "sibling",
    ) -> Concept:
        """Produce a concept that is *genuinely different* from ``original``.

        The agent uses this for semantic relaxation — e.g., when
        "Influenza, Human" returns too few hits, it needs "Common Cold"
        or "Respiratory Tract Infections" to cast a wider net. A resolver
        that hands back "Influenza, Human" again is useless.

        We enforce this two ways: the prompt explicitly demands a DIFFERENT
        MeSH, and the post-hoc validator rejects results whose MeSH set
        overlaps by more than ``_RELATED_OVERLAP_CAP`` with the original's.
        On rejection we retry once; if that also fails, we return a
        concept flagged validated=False with a clear note so the query
        builder can still use its tiab fallback.
        """
        original_mesh = {m.lower() for m in original.mesh_terms}
        original_term = (original.user_term or "").lower()

        for attempt in range(2):
            proposal = self._call_related_llm(
                slot_name, original, direction, attempt
            )
            new_mesh = {m.lower() for m in (proposal.primary_mesh, *(proposal.alternative_mesh or []))}

            if not _is_sufficiently_different(new_mesh, original_mesh, original_term):
                logger.info(
                    "resolve_related attempt %d returned tautology; retrying.",
                    attempt + 1,
                )
                continue

            # Validate like resolve(): at least one MeSH should be productive.
            candidates = [proposal.primary_mesh, *(proposal.alternative_mesh or [])]
            validated_mesh: list[str] = []
            best_effort: Optional[str] = None
            for mesh in candidates[:_MAX_VALIDATIONS]:
                if not mesh or not mesh.strip():
                    continue
                if mesh.lower() in original_mesh:
                    continue  # skip any MeSH that matches the original
                if self._validate_mesh(mesh):
                    validated_mesh.append(mesh)
                elif best_effort is None:
                    best_effort = mesh

            if validated_mesh:
                final_mesh = validated_mesh
                validated_flag = True
            elif best_effort is not None:
                final_mesh = [best_effort]
                validated_flag = False
            else:
                continue  # retry

            synonyms = [
                s for s in (proposal.tiab_synonyms or []) if s and s.strip()
            ]
            return Concept(
                user_term=proposal.primary_mesh or f"related-to-{original.user_term}",
                mesh_terms=final_mesh,
                tiab_synonyms=synonyms,
                validated=validated_flag,
                notes=(
                    f"related ({direction}) to {original.user_term!r}; "
                    f"{proposal.reasoning}"
                ),
            )

        # Both attempts failed — return an empty concept flagged as such.
        return Concept(
            user_term=f"related-{direction}-to-{original.user_term}",
            mesh_terms=[],
            tiab_synonyms=[],
            validated=False,
            notes=(
                f"Could not find a sufficiently different related concept "
                f"after 2 attempts (direction={direction})."
            ),
        )

    def resolve_pico(self, pico: PartialPICO) -> dict[str, Concept]:
        """Resolve every relevant PICO slot in parallel."""
        context = {
            "food": pico.food,
            "outcome": pico.outcome,
            "component": pico.component,
            "population": pico.population,
        }
        slots = [
            (slot, context[slot]) for slot in _RESOLVABLE_SLOTS if context[slot]
        ]
        if not slots:
            return {}

        results: dict[str, Concept] = {}

        def _resolve_one(slot: str, value: str) -> Concept:
            try:
                return self.resolve(
                    slot,
                    value,
                    {k: v for k, v in context.items() if k != slot and v},
                )
            except Exception as exc:
                logger.warning(
                    "Concept resolution failed for slot=%s: %s", slot, exc
                )
                return Concept(
                    user_term=value or "",
                    mesh_terms=[],
                    tiab_synonyms=[value] if value else [],
                    validated=False,
                    notes=f"resolver error: {exc}",
                )

        if self.max_workers == 1:
            # Serial path — safe on Gemini free tier (5 req/min).
            for slot, value in slots:
                results[slot] = _resolve_one(slot, value)
        else:
            with ThreadPoolExecutor(
                max_workers=min(self.max_workers, len(slots))
            ) as pool:
                futures = {
                    pool.submit(_resolve_one, slot, value): slot
                    for slot, value in slots
                }
                for fut in as_completed(futures):
                    slot = futures[fut]
                    results[slot] = fut.result()
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _call_llm(
        self, slot_name: str, user_term: str, context: dict
    ) -> _LLMResolution:
        user_message = (
            f"slot: {slot_name}\n"
            f"user_term: {user_term}\n"
            f"context: {context}"
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        return self.llm.extract(messages, _LLMResolution)  # type: ignore[return-value]

    def _call_related_llm(
        self,
        slot_name: str,
        original: Concept,
        direction: str,
        attempt: int,
    ) -> _LLMResolution:
        direction_hint = _DIRECTION_HINTS.get(direction, direction)
        retry_suffix = ""
        if attempt > 0:
            retry_suffix = (
                "\n\nIMPORTANT: Your previous response returned the same "
                "concept. Return a DIFFERENT MeSH term this time — the goal "
                "is a related but distinct concept."
            )
        user_message = (
            f"slot: {slot_name}\n"
            f"original concept user_term: {original.user_term}\n"
            f"original MeSH: {original.mesh_terms}\n"
            f"direction: {direction} ({direction_hint})\n\n"
            f"Return a DIFFERENT MeSH Heading that is {direction_hint} to "
            f"the original. The primary_mesh you return MUST NOT be any of "
            f"the original MeSH terms."
            f"{retry_suffix}"
        )
        messages = [
            {"role": "system", "content": _RELATED_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        return self.llm.extract(messages, _LLMResolution)  # type: ignore[return-value]

    def _validate_mesh(self, mesh_term: str) -> bool:
        try:
            count = self.pubmed.count(f'"{mesh_term}"[MeSH Terms]')
        except Exception as exc:
            logger.warning(
                "MeSH validation failed for %r (%s); treating as invalid.",
                mesh_term,
                exc,
            )
            return False
        return count >= self.threshold


def _is_sufficiently_different(
    proposed_mesh: set[str],
    original_mesh: set[str],
    original_term: str,
) -> bool:
    """Reject LLM proposals that are tautologies of the original.

    Two failure modes the LLM tends to fall into:
      1. Returning the exact same MeSH Heading(s).
      2. Returning something that paraphrases the original user term.

    We reject if either the MeSH set overlaps ≥ _RELATED_OVERLAP_CAP with
    the original, or the sole proposed MeSH is a case-insensitive variant
    of the original user term.
    """
    proposed_mesh = {m for m in proposed_mesh if m}
    if not proposed_mesh:
        return False
    overlap = len(proposed_mesh & original_mesh) / max(1, len(proposed_mesh))
    if overlap >= _RELATED_OVERLAP_CAP:
        return False
    # Guard against the LLM echoing the user_term as a MeSH.
    if original_term:
        if all(
            m.lower().strip() == original_term
            or original_term in m.lower()
            for m in proposed_mesh
        ):
            return False
    return True
