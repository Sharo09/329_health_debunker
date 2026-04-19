"""Tests for the concept-based QueryBuilder — retrieval spec Task 4."""

from __future__ import annotations

import pytest

from src.retrieval.query_builder import (
    QueryBuilder,
    _concept_block,
    _escape,
)
from src.retrieval.schemas import Concept


# ---------------------------------------------------------------------------
# Fixture concepts
# ---------------------------------------------------------------------------

def _orange_concept() -> Concept:
    return Concept(
        user_term="orange",
        mesh_terms=["Citrus sinensis", "Citrus"],
        tiab_synonyms=["orange", "oranges"],
        validated=True,
    )


def _flu_concept() -> Concept:
    return Concept(
        user_term="flu",
        mesh_terms=["Influenza, Human"],
        tiab_synonyms=["influenza", "flu"],
        validated=True,
    )


def _vitamin_c_concept() -> Concept:
    return Concept(
        user_term="vitamin C",
        mesh_terms=["Ascorbic Acid"],
        tiab_synonyms=["vitamin C", "ascorbic acid"],
        validated=True,
    )


def _common_cold_concept() -> Concept:
    return Concept(
        user_term="common cold",
        mesh_terms=["Common Cold"],
        tiab_synonyms=["common cold"],
        validated=True,
    )


def _adult_concept() -> Concept:
    return Concept(
        user_term="adult",
        mesh_terms=["Adult"],
        tiab_synonyms=[],
        validated=True,
    )


# ---------------------------------------------------------------------------
# The canonical fix — orange/flu direct query
# ---------------------------------------------------------------------------

def test_orange_flu_direct_query_uses_citrus_sinensis_not_orange_mesh():
    """Regression test for the root failure. The old builder produced
    ``"orange"[MeSH Terms]`` (the colour). The new builder must use the
    fruit's MeSH Heading."""
    qb = QueryBuilder()
    concepts = {"food": _orange_concept(), "outcome": _flu_concept()}

    query = qb.build_direct_query(concepts, include_filters=False)

    assert '"Citrus sinensis"[MeSH Terms]' in query
    assert '"Citrus"[MeSH Terms]' in query
    assert '"Influenza, Human"[MeSH Terms]' in query
    # Crucial: the broken literal must NOT appear.
    assert '"orange"[MeSH Terms]' not in query
    assert '"flu"[MeSH Terms]' not in query


# ---------------------------------------------------------------------------
# Structural correctness
# ---------------------------------------------------------------------------

def test_direct_query_joins_food_and_outcome_with_and():
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {"food": _orange_concept(), "outcome": _flu_concept()},
        include_filters=False,
    )
    # Broad check that the top-level glue is AND.
    assert " AND " in query


def test_direct_query_parenthesises_or_blocks():
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {"food": _orange_concept(), "outcome": _flu_concept()},
        include_filters=False,
    )
    # Each multi-term OR-block must be parenthesised so AND can't steal terms.
    assert "(" in query and ")" in query
    assert query.count("(") == query.count(")")


def test_direct_query_adds_humans_and_english_filters_by_default():
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {"food": _orange_concept(), "outcome": _flu_concept()}
    )
    assert "humans[Filter]" in query
    assert "English[Language]" in query


def test_direct_query_without_filters():
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {"food": _orange_concept(), "outcome": _flu_concept()},
        include_filters=False,
    )
    assert "humans[Filter]" not in query
    assert "English[Language]" not in query


def test_direct_query_min_year_clause():
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {"food": _orange_concept(), "outcome": _flu_concept()},
        min_year=2015,
    )
    assert '"2015"[Date - Publication]' in query
    assert '"3000"[Date - Publication]' in query


def test_direct_query_raises_when_both_food_and_outcome_missing():
    qb = QueryBuilder()
    with pytest.raises(ValueError):
        qb.build_direct_query({})


def test_direct_query_works_with_only_food():
    """Spec: food alone still builds if outcome is unresolvable."""
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {"food": _orange_concept()}, include_filters=False
    )
    assert '"Citrus sinensis"[MeSH Terms]' in query


def test_direct_query_works_with_only_outcome():
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {"outcome": _flu_concept()}, include_filters=False
    )
    assert '"Influenza, Human"[MeSH Terms]' in query


def test_direct_query_includes_population_when_present():
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {
            "food": _orange_concept(),
            "outcome": _flu_concept(),
            "population": _adult_concept(),
        },
        include_filters=False,
    )
    assert '"Adult"[MeSH Terms]' in query


def test_direct_query_can_suppress_population_filter():
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {
            "food": _orange_concept(),
            "outcome": _flu_concept(),
            "population": _adult_concept(),
        },
        include_filters=False,
        population_as_filter=False,
    )
    assert '"Adult"[MeSH Terms]' not in query


def test_direct_query_includes_tiab_fallback():
    """Tiab synonyms are OR'd in alongside MeSH to catch papers that don't
    use the controlled vocabulary."""
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {"food": _orange_concept(), "outcome": _flu_concept()},
        include_filters=False,
    )
    assert '"orange"[tiab]' in query
    assert '"influenza"[tiab]' in query


def test_direct_query_with_empty_tiab_synonyms_still_valid():
    """When only MeSH terms are available, the query is still well-formed."""
    qb = QueryBuilder()
    mesh_only = Concept(
        user_term="x",
        mesh_terms=["Some Mesh"],
        tiab_synonyms=[],
        validated=True,
    )
    query = qb.build_direct_query(
        {"food": mesh_only, "outcome": _flu_concept()},
        include_filters=False,
    )
    assert '"Some Mesh"[MeSH Terms]' in query
    # No trailing empty tiab block or dangling OR.
    assert query.count("(") == query.count(")")
    assert "[tiab]" not in query.split("Influenza, Human")[0]


# ---------------------------------------------------------------------------
# Mechanism query (the missing-vitamin-C fix)
# ---------------------------------------------------------------------------

def test_mechanism_query_uses_component_and_outcome():
    qb = QueryBuilder()
    query = qb.build_mechanism_query(
        {"component": _vitamin_c_concept(), "outcome": _flu_concept()},
        include_filters=False,
    )
    assert '"Ascorbic Acid"[MeSH Terms]' in query
    assert '"Influenza, Human"[MeSH Terms]' in query


def test_mechanism_query_returns_none_without_component():
    qb = QueryBuilder()
    assert (
        qb.build_mechanism_query(
            {"food": _orange_concept(), "outcome": _flu_concept()}
        )
        is None
    )


def test_mechanism_query_returns_none_without_outcome():
    qb = QueryBuilder()
    assert (
        qb.build_mechanism_query(
            {"component": _vitamin_c_concept()}
        )
        is None
    )


def test_mechanism_query_returns_none_when_component_has_no_terms():
    qb = QueryBuilder()
    empty_concept = Concept(
        user_term="", mesh_terms=[], tiab_synonyms=[], validated=False
    )
    assert (
        qb.build_mechanism_query(
            {"component": empty_concept, "outcome": _flu_concept()}
        )
        is None
    )


# ---------------------------------------------------------------------------
# Related-outcome relaxation
# ---------------------------------------------------------------------------

def test_related_outcome_query_swaps_outcome_for_related():
    qb = QueryBuilder()
    query = qb.build_related_outcome_query(
        {"food": _orange_concept(), "outcome": _flu_concept()},
        related_outcome=_common_cold_concept(),
        include_filters=False,
    )
    assert '"Citrus sinensis"[MeSH Terms]' in query
    assert '"Common Cold"[MeSH Terms]' in query
    # The original (not-related) outcome must NOT appear.
    assert '"Influenza, Human"[MeSH Terms]' not in query


def test_related_outcome_query_raises_without_food():
    qb = QueryBuilder()
    with pytest.raises(ValueError):
        qb.build_related_outcome_query({}, related_outcome=_common_cold_concept())


# ---------------------------------------------------------------------------
# Study-type filter
# ---------------------------------------------------------------------------

def test_study_type_filter_tier_1_includes_sr_and_meta_analysis():
    qb = QueryBuilder()
    clause = qb.build_study_type_filter([1])
    assert '"systematic review"[Publication Type]' in clause
    assert '"meta-analysis"[Publication Type]' in clause


def test_study_type_filter_tier_1_and_2_includes_rct():
    qb = QueryBuilder()
    clause = qb.build_study_type_filter([1, 2])
    assert '"randomized controlled trial"[Publication Type]' in clause
    assert '"meta-analysis"[Publication Type]' in clause


def test_study_type_filter_empty_tiers_is_empty_string():
    qb = QueryBuilder()
    assert qb.build_study_type_filter([]) == ""
    assert qb.build_study_type_filter([4]) == ""


def test_study_type_filter_unknown_tier_silently_ignored():
    qb = QueryBuilder()
    assert qb.build_study_type_filter([99]) == ""


# ---------------------------------------------------------------------------
# Escaping / safety
# ---------------------------------------------------------------------------

def test_escape_strips_brackets_and_quotes():
    assert _escape('weird"term') == "weirdterm"
    assert _escape("bracket[thing]") == "bracketthing"


def test_concept_with_hostile_characters_still_produces_valid_query():
    qb = QueryBuilder()
    hostile = Concept(
        user_term='bad"stuff',
        mesh_terms=['Mesh[with]brackets'],
        tiab_synonyms=['double"quotes'],
        validated=True,
    )
    query = qb.build_direct_query(
        {"food": hostile, "outcome": _flu_concept()},
        include_filters=False,
    )
    # Equal counts of `(` and `)` → still parenthesis-balanced.
    assert query.count("(") == query.count(")")
    # Hostile characters stripped.
    assert "[with]" not in query
    assert '"' in query  # the legitimate phrase quotes remain


# ---------------------------------------------------------------------------
# Regression for orange/flu: full assembled query sanity
# ---------------------------------------------------------------------------

def test_orange_flu_full_assembled_query_looks_right():
    qb = QueryBuilder()
    query = qb.build_direct_query(
        {"food": _orange_concept(), "outcome": _flu_concept()}
    )

    # All expected pieces present.
    for piece in (
        '"Citrus sinensis"[MeSH Terms]',
        '"Influenza, Human"[MeSH Terms]',
        '"orange"[tiab]',
        '"influenza"[tiab]',
        "humans[Filter]",
        "English[Language]",
        " AND ",
    ):
        assert piece in query, f"missing {piece!r} in {query!r}"

    # Balanced parens.
    assert query.count("(") == query.count(")")
