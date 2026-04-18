"""Concept-based PubMed query builder (retrieval spec Task 4).

Turns a dict of resolved ``Concept`` objects into Boolean PubMed queries.
Replaces the old string-concatenation builder that produced broken
queries like ``"orange"[MeSH Terms]`` (the colour, not the fruit).

The builder is the **single source of truth for PubMed query syntax**.
The retrieval agent never constructs raw query strings — it composes
concepts and calls into this module.

Kept in its own file so Sharon's legacy ``query_builder.py`` and her
``retrieval_agent.py`` keep working until Task 6 consolidates.
"""

from __future__ import annotations

import re
from typing import Optional

from src.retrieval.schemas import Concept

# ---------------------------------------------------------------------------
# Study-design tiers → PubMed publication types
# ---------------------------------------------------------------------------

STUDY_TYPES_BY_TIER: dict[int, list[str]] = {
    1: ["systematic review", "meta-analysis"],
    2: ["randomized controlled trial"],
    3: ["observational study", "cohort studies", "case-control studies"],
    4: [],  # no filter at this tier — everything is allowed
}


# ---------------------------------------------------------------------------
# QueryBuilder
# ---------------------------------------------------------------------------

class QueryBuilder:
    """Translate resolved concepts into PubMed Boolean query strings.

    All ``build_*`` methods accept a dict of ``Concept`` objects keyed by
    slot name (``"food"``, ``"outcome"``, ``"component"``, ``"population"``).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_direct_query(
        self,
        concepts: dict[str, Concept],
        include_filters: bool = True,
        min_year: Optional[int] = None,
        population_as_filter: bool = True,
    ) -> str:
        """Primary query: food AND outcome, plus optional filters.

        Raises ``ValueError`` if neither food nor outcome is resolvable.
        """
        food = concepts.get("food")
        outcome = concepts.get("outcome")
        if not _has_terms(food) and not _has_terms(outcome):
            raise ValueError(
                "Cannot build direct query: need at least one of food or outcome."
            )
        return self._assemble(
            food, outcome,
            population=concepts.get("population") if population_as_filter else None,
            include_filters=include_filters,
            min_year=min_year,
        )

    def build_mechanism_query(
        self,
        concepts: dict[str, Concept],
        include_filters: bool = True,
        min_year: Optional[int] = None,
        population_as_filter: bool = True,
    ) -> Optional[str]:
        """Mechanism query: component AND outcome.

        Returns ``None`` if no component concept was resolved — this is
        the explicit signal the retrieval agent uses to decide whether
        the mechanism strategy is available.
        """
        component = concepts.get("component")
        outcome = concepts.get("outcome")
        if not _has_terms(component) or not _has_terms(outcome):
            return None
        return self._assemble(
            component, outcome,
            population=concepts.get("population") if population_as_filter else None,
            include_filters=include_filters,
            min_year=min_year,
        )

    def build_related_outcome_query(
        self,
        concepts: dict[str, Concept],
        related_outcome: Concept,
        include_filters: bool = True,
        min_year: Optional[int] = None,
        population_as_filter: bool = True,
    ) -> str:
        """Food AND a semantically-related outcome concept.

        Used for *semantic* relaxation. For orange/flu, a related outcome
        might be "Common Cold" or "Upper Respiratory Tract Infections".
        """
        food = concepts.get("food")
        if not _has_terms(food):
            raise ValueError("Cannot build related-outcome query: food is required.")
        if not _has_terms(related_outcome):
            raise ValueError("Cannot build related-outcome query: related_outcome has no terms.")
        return self._assemble(
            food, related_outcome,
            population=concepts.get("population") if population_as_filter else None,
            include_filters=include_filters,
            min_year=min_year,
        )

    def build_study_type_filter(self, tiers: list[int]) -> str:
        """Return an OR-block matching any publication type in the given tiers.

        Empty tiers or unrecognised tiers simply contribute no clause.
        Returns an empty string when no study-type filter should be applied.
        """
        pub_types: list[str] = []
        for tier in tiers:
            pub_types.extend(STUDY_TYPES_BY_TIER.get(tier, []))
        if not pub_types:
            return ""
        clauses = [f'"{pt}"[Publication Type]' for pt in pub_types]
        return _or_group(clauses)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _assemble(
        self,
        left: Optional[Concept],
        right: Optional[Concept],
        population: Optional[Concept],
        include_filters: bool,
        min_year: Optional[int],
    ) -> str:
        parts: list[str] = []
        left_block = _concept_block(left)
        right_block = _concept_block(right)
        if left_block:
            parts.append(left_block)
        if right_block:
            parts.append(right_block)

        # Population, when available, goes in as an extra filter term.
        if population is not None and _has_terms(population):
            parts.append(_concept_block(population))

        if include_filters:
            parts.append("humans[Filter]")
            parts.append("English[Language]")

        if min_year is not None:
            parts.append(
                f'("{min_year}"[Date - Publication] : "3000"[Date - Publication])'
            )

        return " AND ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_terms(concept: Optional[Concept]) -> bool:
    if concept is None:
        return False
    return bool(concept.mesh_terms) or bool(concept.tiab_synonyms)


def _concept_block(concept: Optional[Concept]) -> str:
    """Build ``((mesh_1[MeSH] OR mesh_2[MeSH]) OR (syn_1[tiab] OR syn_2[tiab]))``."""
    if concept is None:
        return ""

    mesh_clauses = [
        f'"{_escape(m)}"[MeSH Terms]' for m in concept.mesh_terms if m and m.strip()
    ]
    tiab_clauses = [
        f'"{_escape(s)}"[tiab]' for s in concept.tiab_synonyms if s and s.strip()
    ]

    groups: list[str] = []
    if mesh_clauses:
        groups.append(_or_group(mesh_clauses))
    if tiab_clauses:
        groups.append(_or_group(tiab_clauses))

    if not groups:
        return ""
    if len(groups) == 1:
        return groups[0]
    return "(" + " OR ".join(groups) + ")"


def _or_group(clauses: list[str]) -> str:
    """Parenthesise an OR-joined group. Single clauses need no extra parens."""
    if len(clauses) == 1:
        return clauses[0]
    return "(" + " OR ".join(clauses) + ")"


# Characters that would break PubMed's quoted phrase parser.
_BAD_CHARS_RE = re.compile(r'[\[\]"]')


def _escape(term: str) -> str:
    """Strip characters that break PubMed's quoted-phrase grammar."""
    # We quote with double quotes (`"term"`). Any brackets or embedded quotes
    # inside `term` would break the grammar. Strip them — losing precision on
    # exotic terms is better than producing a syntactically-invalid query.
    return _BAD_CHARS_RE.sub("", term).strip()
