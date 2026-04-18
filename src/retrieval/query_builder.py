"""Converts a ``LockedPICO`` into a PubMed E-utilities query string.

PubMed query syntax:
    term[Field]  — e.g. "curcumin"[MeSH Terms], "inflammation"[tiab]
    AND / OR / NOT (uppercase)
    Parentheses group sub-expressions.

Design
------
The builder supports six relaxation levels. The agent tries each in order
until the result count passes the minimum threshold:

    FULL           food + component + outcome + population + form
    DROP_FORM      drop form and frequency terms
    DROP_POPULATION  drop population filter
    CORE           food / component + outcome only
    MESH_ONLY      MeSH-controlled terms only (no free-text [tiab])
    BROAD          single food term + outcome, no filters at all
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Relaxation levels
# ---------------------------------------------------------------------------

class RelaxationLevel(IntEnum):
    FULL = 0
    DROP_FORM = 1
    DROP_POPULATION = 2
    CORE = 3
    MESH_ONLY = 4
    BROAD = 5


# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

# Maps canonical food names (lowercase) to lists of PubMed search terms.
# Station 1's food_normalizer ensures the food field is already canonical.
FOOD_SYNONYMS: dict[str, list[str]] = {
    "turmeric":              ["turmeric", "curcuma longa", "curcumin"],
    "coffee":                ["coffee", "coffea", "caffeine"],
    "red meat":              ["red meat", "beef", "pork", "lamb", "processed meat"],
    "eggs":                  ["eggs", "egg consumption", "dietary cholesterol"],
    "alcohol":               ["alcohol", "ethanol", "alcoholic beverages"],
    "vitamin d":             ["vitamin D", "cholecalciferol", "ergocalciferol"],
    "intermittent fasting":  ["intermittent fasting", "time-restricted eating",
                              "alternate day fasting"],
    "artificial sweeteners": ["artificial sweeteners", "non-nutritive sweeteners",
                              "saccharin", "aspartame", "sucralose"],
    "added sugar":           ["added sugar", "sucrose", "fructose",
                              "high-fructose corn syrup"],
    "dairy milk":            ["dairy milk", "cow's milk", "milk consumption", "lactose"],
}

# Maps population slot values → PubMed MeSH filter.
# Station 2 stores values with underscores (e.g. "healthy_adults"); we
# normalise by replacing underscores with spaces before lookup.
POPULATION_MESH: dict[str, str] = {
    "healthy adults":               "adult[MeSH Terms]",
    "elderly":                      "aged[MeSH Terms]",
    "older adults (65+)":           "aged[MeSH Terms]",
    "pregnant or breastfeeding":    "pregnant women[MeSH Terms]",
    "pregnant women":               "pregnant women[MeSH Terms]",
    "children":                     "child[MeSH Terms]",
    "adolescents":                  "adolescent[MeSH Terms]",
    "athletes":                     "athletes[tiab]",
    "obese":                        "obesity[MeSH Terms]",
    "diabetic":                     "diabetes mellitus[MeSH Terms]",
    "people with arthritis or inflammatory disease":
                                    "arthritis[MeSH Terms]",
}

# Maps form slot values → lists of PubMed [tiab] terms.
# Station 2's question_templates determine the exact strings stored here.
FORM_TERMS: dict[str, list[str]] = {
    "supplement":                   ["supplement[tiab]", "capsule[tiab]", "extract[tiab]"],
    "dietary":                      ["dietary[tiab]", "food[tiab]", "consumption[tiab]"],
    "extract":                      ["extract[tiab]", "standardized extract[tiab]"],
    # Values as stored by Station 2 question templates:
    "as a spice in food (typical culinary amounts)":
                                    ["dietary[tiab]", "food intake[tiab]", "culinary[tiab]"],
    "as a curcumin supplement (standardized extract pills)":
                                    ["supplement[tiab]", "curcumin[tiab]", "extract[tiab]"],
    "turmeric tea or golden milk":  ["turmeric tea[tiab]", "golden milk[tiab]"],
}


# ---------------------------------------------------------------------------
# QueryBuilder
# ---------------------------------------------------------------------------

class QueryBuilder:
    """Translates a ``LockedPICO`` (flat string fields) into a PubMed query."""

    def build(self, pico, level: RelaxationLevel) -> str:
        """
        Return a PubMed query string for the given relaxation level.

        Parameters
        ----------
        pico  : LockedPICO  (from src.schemas)
        level : RelaxationLevel

        Raises
        ------
        ValueError  if neither a food block nor an outcome block can be built.
        """
        parts: list[str] = []

        food_block = self._food_block(pico, level)
        if food_block:
            parts.append(food_block)

        outcome_block = self._outcome_block(pico)
        if outcome_block:
            parts.append(outcome_block)

        if not parts:
            raise ValueError(
                "Cannot build any PubMed query: LockedPICO has no food and no outcome."
            )

        # Form filter — only at FULL and DROP_POPULATION levels
        if level <= RelaxationLevel.DROP_FORM:
            form_block = self._form_block(pico)
            if form_block:
                parts.append(form_block)

        # Population filter — only at FULL and DROP_FORM levels
        if level <= RelaxationLevel.DROP_POPULATION:
            pop_block = self._population_block(pico)
            if pop_block:
                parts.append(pop_block)

        # Human filter — all levels except BROAD
        if level < RelaxationLevel.BROAD:
            parts.append("humans[MeSH Terms]")

        # English filter — only at the stricter levels
        if level <= RelaxationLevel.DROP_POPULATION:
            parts.append("English[Language]")

        return " AND ".join(
            f"({p})" if (" OR " in p or " AND " in p) else p
            for p in parts
        )

    # --- sub-builders ---

    def _food_block(self, pico, level: RelaxationLevel) -> Optional[str]:
        """
        Build the food/component OR-block.

        At MESH_ONLY level we suppress [tiab] terms to force the query
        through the controlled MeSH vocabulary. This often recovers results
        when free-text searches are too noisy.
        """
        terms: list[str] = []
        food_key = (pico.food or "").strip().lower()
        synonyms = FOOD_SYNONYMS.get(food_key, [pico.food] if pico.food else [])

        for syn in synonyms:
            terms.append(f'"{syn}"[MeSH Terms]')
            if level != RelaxationLevel.MESH_ONLY:
                terms.append(f'"{syn}"[tiab]')

        # Add explicit component (e.g. "curcumin") if Station 2 filled it in
        # and it's not already covered by the synonym list.
        if pico.component:
            comp = pico.component.strip().lower()
            already_covered = any(comp in s.lower() for s in synonyms)
            if not already_covered:
                terms.append(f'"{pico.component}"[MeSH Terms]')
                if level != RelaxationLevel.MESH_ONLY:
                    terms.append(f'"{pico.component}"[tiab]')

        if not terms:
            return None

        # De-duplicate while preserving insertion order
        seen: set[str] = set()
        unique = [t for t in terms if not (t in seen or seen.add(t))]
        return " OR ".join(unique)

    def _outcome_block(self, pico) -> Optional[str]:
        if not pico.outcome:
            return None
        outcome = pico.outcome.strip()
        return f'"{outcome}"[MeSH Terms] OR "{outcome}"[tiab]'

    def _form_block(self, pico) -> Optional[str]:
        if not pico.form:
            return None
        form_key = pico.form.strip().lower()
        terms = FORM_TERMS.get(form_key)
        if terms:
            return " OR ".join(terms)
        # Unknown form value: fall back to free-text search
        logger.debug("Unknown form value %r; using free-text fallback.", pico.form)
        return f'"{pico.form}"[tiab]'

    def _population_block(self, pico) -> Optional[str]:
        if not pico.population:
            return None
        # Station 2 stores underscores (e.g. "healthy_adults"); normalise.
        pop_key = pico.population.strip().lower().replace("_", " ")
        mesh = POPULATION_MESH.get(pop_key)
        if mesh:
            return mesh
        # Free-text fallback for populations not in our lookup table
        logger.debug("Unknown population %r; using free-text fallback.", pico.population)
        return f'"{pico.population.replace("_", " ")}"[tiab]'