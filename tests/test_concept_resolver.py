"""Tests for the concept resolver — retrieval spec Task 3.

The critical case is the orange/flu failure: user says "orange" in a
food claim → must resolve to Citrus sinensis (the fruit), not the
colour. User says "flu" → must resolve to "Influenza, Human".
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.extraction.llm_client import LLMClient
from src.retrieval.concept_resolver import (
    VALIDATION_THRESHOLD,
    ConceptResolver,
    _LLMResolution,
)
from src.retrieval.schemas import Concept
from src.schemas import PartialPICO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _llm_with_responses(*responses: dict):
    """LLMClient whose provider yields pre-baked JSON objects."""
    pending = [json.dumps(r) for r in responses]

    def provider(messages, response_schema, model, temperature):
        if not pending:
            raise AssertionError("LLM provider ran out of scripted responses")
        return pending.pop(0)

    return LLMClient(provider=provider, log_file="/tmp/concept_resolver_test.jsonl")


def _mock_pubmed(counts: dict[str, int] | int = 1000):
    """A PubMedClient double whose ``count()`` returns controlled values.

    Pass an int for a flat return; pass a dict to simulate different
    counts per query (key-substring match).
    """
    m = MagicMock()
    if isinstance(counts, int):
        m.count.return_value = counts
    else:
        def _count(query: str) -> int:
            for needle, c in counts.items():
                if needle in query:
                    return c
            return 0
        m.count.side_effect = _count
    return m


# ---------------------------------------------------------------------------
# Core happy paths
# ---------------------------------------------------------------------------

def test_orange_in_food_context_resolves_to_citrus_sinensis():
    """The canonical fix: 'orange' + food + context=flu must NOT map to the colour."""
    llm = _llm_with_responses({
        "primary_mesh": "Citrus sinensis",
        "alternative_mesh": ["Citrus"],
        "tiab_synonyms": ["orange", "oranges", "sweet orange"],
        "reasoning": "In a food claim, 'orange' is the fruit.",
    })
    pubmed = _mock_pubmed(counts={"Citrus sinensis": 5000, "Citrus": 20000})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("food", "orange", context={"outcome": "flu"})

    assert "Citrus sinensis" in concept.mesh_terms
    assert concept.validated is True
    assert "orange" in [s.lower() for s in concept.tiab_synonyms]


def test_flu_resolves_to_influenza_human():
    llm = _llm_with_responses({
        "primary_mesh": "Influenza, Human",
        "alternative_mesh": ["Orthomyxoviridae Infections"],
        "tiab_synonyms": ["influenza", "flu"],
        "reasoning": "MeSH Heading for flu is Influenza, Human.",
    })
    pubmed = _mock_pubmed(counts={"Influenza, Human": 90000})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("outcome", "flu", context={"food": "orange"})

    assert concept.mesh_terms == ["Influenza, Human"]
    assert concept.validated is True
    assert "flu" in [s.lower() for s in concept.tiab_synonyms]


def test_vitamin_c_resolves_to_ascorbic_acid():
    llm = _llm_with_responses({
        "primary_mesh": "Ascorbic Acid",
        "alternative_mesh": [],
        "tiab_synonyms": ["vitamin C", "ascorbic acid", "ascorbate"],
        "reasoning": "MeSH Heading for vitamin C.",
    })
    pubmed = _mock_pubmed(counts={"Ascorbic Acid": 45000})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve(
        "component", "vitamin C", context={"food": "orange", "outcome": "flu"}
    )

    assert concept.mesh_terms == ["Ascorbic Acid"]
    assert concept.validated is True


def test_curcumin_resolves_to_curcumin_mesh():
    llm = _llm_with_responses({
        "primary_mesh": "Curcumin",
        "alternative_mesh": ["Curcuma"],
        "tiab_synonyms": ["curcumin", "curcuma longa"],
        "reasoning": "Curcumin is its own MeSH.",
    })
    pubmed = _mock_pubmed(counts={"Curcumin": 15000, "Curcuma": 3000})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("component", "curcumin", context={"food": "turmeric"})

    assert "Curcumin" in concept.mesh_terms
    assert concept.validated is True


def test_miscarriage_resolves_to_spontaneous_abortion():
    llm = _llm_with_responses({
        "primary_mesh": "Abortion, Spontaneous",
        "alternative_mesh": ["Pregnancy Complications"],
        "tiab_synonyms": ["miscarriage", "spontaneous abortion"],
        "reasoning": "MeSH: Abortion, Spontaneous.",
    })
    pubmed = _mock_pubmed(counts={"Abortion, Spontaneous": 25000})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve(
        "outcome", "miscarriage", context={"food": "coffee"}
    )

    assert concept.mesh_terms == ["Abortion, Spontaneous"]


def test_red_meat_resolves_to_its_real_mesh():
    llm = _llm_with_responses({
        "primary_mesh": "Red Meat",
        "alternative_mesh": ["Meat"],
        "tiab_synonyms": ["red meat", "beef", "pork"],
        "reasoning": "Red Meat is a real MeSH Heading.",
    })
    pubmed = _mock_pubmed(counts={"Red Meat": 4000, "Meat": 80000})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("food", "red meat", context={"outcome": "cancer"})

    assert "Red Meat" in concept.mesh_terms
    assert concept.validated is True


# ---------------------------------------------------------------------------
# Validation fallback
# ---------------------------------------------------------------------------

def test_primary_mesh_below_threshold_falls_through_to_alternative():
    """If the primary MeSH returns too few hits, use the first alternative that passes."""
    llm = _llm_with_responses({
        "primary_mesh": "Fake Mesh Term",
        "alternative_mesh": ["Real Mesh Term"],
        "tiab_synonyms": ["x"],
        "reasoning": "...",
    })
    pubmed = _mock_pubmed(counts={"Fake Mesh Term": 5, "Real Mesh Term": 5000})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("food", "x")

    assert "Real Mesh Term" in concept.mesh_terms
    assert "Fake Mesh Term" not in concept.mesh_terms
    assert concept.validated is True


def test_all_mesh_fail_returns_best_effort_not_validated():
    """If everything fails validation, keep the primary as best-effort and flag validated=False."""
    llm = _llm_with_responses({
        "primary_mesh": "Primary Junk",
        "alternative_mesh": ["Alt Junk"],
        "tiab_synonyms": ["user thing"],
        "reasoning": "...",
    })
    pubmed = _mock_pubmed(counts={"Primary Junk": 5, "Alt Junk": 2})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("food", "user thing")

    assert concept.validated is False
    assert concept.mesh_terms == ["Primary Junk"]
    assert "user thing" in concept.tiab_synonyms


def test_validation_threshold_is_respected():
    llm = _llm_with_responses({
        "primary_mesh": "Borderline",
        "alternative_mesh": [],
        "tiab_synonyms": ["x"],
        "reasoning": "",
    })
    # Exactly at threshold — should be considered valid.
    pubmed = _mock_pubmed(counts={"Borderline": VALIDATION_THRESHOLD})
    resolver = ConceptResolver(llm, pubmed)
    concept = resolver.resolve("food", "x")
    assert concept.validated is True

    # Just under — should be invalid.
    pubmed2 = _mock_pubmed(counts={"Borderline": VALIDATION_THRESHOLD - 1})
    llm2 = _llm_with_responses({
        "primary_mesh": "Borderline",
        "alternative_mesh": [],
        "tiab_synonyms": ["x"],
        "reasoning": "",
    })
    resolver2 = ConceptResolver(llm2, pubmed2)
    concept2 = resolver2.resolve("food", "x")
    assert concept2.validated is False


def test_validation_capped_to_max_calls():
    """A chatty LLM with 10 alternatives must not cause 10 PubMed calls."""
    llm = _llm_with_responses({
        "primary_mesh": "A",
        "alternative_mesh": [f"Alt{i}" for i in range(10)],
        "tiab_synonyms": ["x"],
        "reasoning": "",
    })
    # Nothing validates — forces the resolver to try everything.
    pubmed = _mock_pubmed(counts={})
    resolver = ConceptResolver(llm, pubmed)

    resolver.resolve("food", "x")

    # 1 primary + up to 3 alternatives = 4 calls max.
    assert pubmed.count.call_count <= 4


# ---------------------------------------------------------------------------
# Context is passed to the LLM
# ---------------------------------------------------------------------------

def test_context_is_included_in_llm_prompt():
    """Verify the user message contains the disambiguation context."""
    captured_messages: list[list[dict]] = []

    def provider(messages, response_schema, model, temperature):
        captured_messages.append(messages)
        return json.dumps({
            "primary_mesh": "Citrus sinensis",
            "alternative_mesh": [],
            "tiab_synonyms": ["orange"],
            "reasoning": "",
        })

    llm = LLMClient(provider=provider, log_file="/tmp/concept_resolver_test.jsonl")
    pubmed = _mock_pubmed(counts={"Citrus sinensis": 5000})
    resolver = ConceptResolver(llm, pubmed)

    resolver.resolve("food", "orange", context={"outcome": "flu"})

    user_msg = captured_messages[0][-1]["content"]
    assert "orange" in user_msg
    assert "food" in user_msg
    assert "flu" in user_msg  # context is visible


def test_slot_name_is_visible_to_llm():
    captured_messages: list[list[dict]] = []

    def provider(messages, response_schema, model, temperature):
        captured_messages.append(messages)
        return json.dumps({
            "primary_mesh": "Something",
            "alternative_mesh": [],
            "tiab_synonyms": [],
            "reasoning": "",
        })

    llm = LLMClient(provider=provider, log_file="/tmp/concept_resolver_test.jsonl")
    pubmed = _mock_pubmed(counts={"Something": 5000})
    resolver = ConceptResolver(llm, pubmed)
    resolver.resolve("outcome", "something")

    user_msg = captured_messages[0][-1]["content"]
    assert "outcome" in user_msg.lower()


# ---------------------------------------------------------------------------
# resolve_pico
# ---------------------------------------------------------------------------

def test_resolve_pico_resolves_all_present_slots():
    llm = _llm_with_responses(
        {"primary_mesh": "Citrus sinensis", "alternative_mesh": [], "tiab_synonyms": ["orange"], "reasoning": ""},
        {"primary_mesh": "Influenza, Human", "alternative_mesh": [], "tiab_synonyms": ["flu"], "reasoning": ""},
        {"primary_mesh": "Ascorbic Acid", "alternative_mesh": [], "tiab_synonyms": ["vitamin C"], "reasoning": ""},
        {"primary_mesh": "Adult", "alternative_mesh": [], "tiab_synonyms": ["adult"], "reasoning": ""},
    )
    pubmed = _mock_pubmed(counts={
        "Citrus sinensis": 5000,
        "Influenza, Human": 90000,
        "Ascorbic Acid": 45000,
        "Adult": 1_000_000,
    })
    resolver = ConceptResolver(llm, pubmed)

    pico = PartialPICO(
        raw_claim="does orange prevent flu",
        food="orange",
        outcome="flu",
        component="vitamin C",
        population="adult",
    )
    concepts = resolver.resolve_pico(pico)

    assert set(concepts.keys()) == {"food", "outcome", "component", "population"}
    assert "Citrus sinensis" in concepts["food"].mesh_terms
    assert "Influenza, Human" in concepts["outcome"].mesh_terms
    assert "Ascorbic Acid" in concepts["component"].mesh_terms
    assert "Adult" in concepts["population"].mesh_terms


def test_resolve_pico_skips_missing_slots():
    llm = _llm_with_responses(
        {"primary_mesh": "Citrus sinensis", "alternative_mesh": [], "tiab_synonyms": ["orange"], "reasoning": ""},
        {"primary_mesh": "Influenza, Human", "alternative_mesh": [], "tiab_synonyms": ["flu"], "reasoning": ""},
    )
    pubmed = _mock_pubmed(counts={"Citrus sinensis": 5000, "Influenza, Human": 90000})
    resolver = ConceptResolver(llm, pubmed)

    pico = PartialPICO(
        raw_claim="does orange prevent flu",
        food="orange",
        outcome="flu",
        # no component, no population
    )
    concepts = resolver.resolve_pico(pico)

    assert set(concepts.keys()) == {"food", "outcome"}


def test_resolve_pico_survives_one_slot_failure():
    """If one slot blows up, the others should still resolve."""
    call_count = [0]

    def provider(messages, response_schema, model, temperature):
        call_count[0] += 1
        # Alternate between good response and raise
        if call_count[0] == 1:
            return json.dumps({
                "primary_mesh": "Citrus sinensis",
                "alternative_mesh": [],
                "tiab_synonyms": ["orange"],
                "reasoning": "",
            })
        raise RuntimeError("LLM exploded")

    llm = LLMClient(provider=provider, log_file="/tmp/concept_resolver_test.jsonl")
    pubmed = _mock_pubmed(counts={"Citrus sinensis": 5000})
    resolver = ConceptResolver(llm, pubmed)

    pico = PartialPICO(raw_claim="x", food="orange", outcome="flu")
    concepts = resolver.resolve_pico(pico)

    # Both slots present in the output; outcome gets a placeholder concept.
    assert "food" in concepts
    assert "outcome" in concepts
    assert concepts["outcome"].validated is False
    assert concepts["food"].validated is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_user_term_returns_empty_concept_without_llm_call():
    calls = [0]

    def provider(messages, response_schema, model, temperature):
        calls[0] += 1
        raise AssertionError("LLM should not be called for empty term")

    llm = LLMClient(provider=provider, log_file="/tmp/concept_resolver_test.jsonl")
    pubmed = MagicMock()
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("food", "")

    assert concept.mesh_terms == []
    assert concept.validated is False
    assert calls[0] == 0
    assert pubmed.count.call_count == 0


def test_tiab_synonyms_always_include_the_user_term():
    """So the query builder has something to fall back on even if MeSH fails."""
    llm = _llm_with_responses({
        "primary_mesh": "Useless Mesh",
        "alternative_mesh": [],
        "tiab_synonyms": [],
        "reasoning": "",
    })
    pubmed = _mock_pubmed(counts={"Useless Mesh": 0})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("food", "exotic fruit")

    assert "exotic fruit" in concept.tiab_synonyms


def test_synonyms_deduplicated_case_insensitively():
    llm = _llm_with_responses({
        "primary_mesh": "X",
        "alternative_mesh": [],
        "tiab_synonyms": ["Orange", "orange", "oranges", "ORANGE"],
        "reasoning": "",
    })
    pubmed = _mock_pubmed(counts={"X": 10000})
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("food", "orange")

    # Lowercased, each synonym appears at most once.
    lowers = [s.lower() for s in concept.tiab_synonyms]
    assert lowers.count("orange") == 1
    assert "oranges" in lowers


def test_pubmed_count_error_is_swallowed_not_raised():
    """A PubMed error during validation shouldn't kill the whole resolution."""
    llm = _llm_with_responses({
        "primary_mesh": "Some Mesh",
        "alternative_mesh": ["Alt"],
        "tiab_synonyms": ["term"],
        "reasoning": "",
    })
    pubmed = MagicMock()
    pubmed.count.side_effect = RuntimeError("pubmed down")
    resolver = ConceptResolver(llm, pubmed)

    concept = resolver.resolve("food", "term")

    assert concept.validated is False
    # Best-effort MeSH still preserved so the query builder isn't empty-handed.
    assert concept.mesh_terms == ["Some Mesh"]
