"""Tests for AdaptiveElicitationAgent — literature-informed elicitation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.elicitation.adaptive_elicitor import (
    AdaptiveElicitationAgent,
    ProbeSlice,
)
from src.elicitation.errors import (
    InsufficientElicitationError,
    UnscopableClaimError,
)
from src.retrieval.schemas import Concept
from src.schemas import PartialPICO
from tests.fixtures import MockUIAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _orange() -> Concept:
    return Concept(
        user_term="orange",
        mesh_terms=["Citrus sinensis"],
        tiab_synonyms=["orange"],
        validated=True,
    )


def _flu() -> Concept:
    return Concept(
        user_term="flu",
        mesh_terms=["Influenza, Human"],
        tiab_synonyms=["flu", "influenza"],
        validated=True,
    )


def _vitamin_c() -> Concept:
    return Concept(
        user_term="vitamin C",
        mesh_terms=["Ascorbic Acid"],
        tiab_synonyms=["vitamin C"],
        validated=True,
    )


def _common_cold() -> Concept:
    return Concept(
        user_term="common cold",
        mesh_terms=["Common Cold"],
        tiab_synonyms=["common cold"],
        validated=True,
    )


def _resp_infections() -> Concept:
    return Concept(
        user_term="respiratory tract infections",
        mesh_terms=["Respiratory Tract Infections"],
        tiab_synonyms=["respiratory infections"],
        validated=True,
    )


def _make_agent(*, ui, pubmed_counts, resolver_concepts, related, tmp_log):
    """Wire up an agent with controlled probe responses.

    ``pubmed_counts`` keys can be either a string (single substring that
    must appear in the query) or a tuple of substrings (ALL must appear).
    The most-specific match wins (longest tuple).
    """
    pubmed = MagicMock()

    def _count(query):
        best_count = 0
        best_specificity = 0
        for needle, count in pubmed_counts.items():
            if isinstance(needle, tuple):
                if all(s in query for s in needle) and len(needle) > best_specificity:
                    best_count = count
                    best_specificity = len(needle)
            else:
                if needle in query and 1 > best_specificity:
                    best_count = count
                    best_specificity = 1
        return best_count

    pubmed.count.side_effect = _count

    resolver = MagicMock()
    resolver.resolve_pico.return_value = resolver_concepts
    resolver.resolve_related.side_effect = lambda slot, original, direction: (
        related.get(direction)
        or Concept(user_term="x", mesh_terms=[], tiab_synonyms=[], validated=False)
    )
    # For population re-resolution
    resolver.resolve.side_effect = lambda slot, term, context=None: (
        related.get("__by_term__", {}).get(term)
        or Concept(user_term=term, mesh_terms=[term.title()], tiab_synonyms=[term], validated=True)
    )

    return AdaptiveElicitationAgent(
        ui_adapter=ui,
        pubmed=pubmed,
        resolver=resolver,
        log_file=str(tmp_log),
        max_probes=15,
        max_questions=3,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_no_food_raises_unscopable(tmp_path):
    ui = MockUIAdapter([])
    agent = _make_agent(
        ui=ui,
        pubmed_counts={},
        resolver_concepts={},
        related={},
        tmp_log=tmp_path / "e.jsonl",
    )
    with pytest.raises(UnscopableClaimError):
        agent.elicit(PartialPICO(raw_claim="x", food=None, ambiguous_slots=[]))


# ---------------------------------------------------------------------------
# High-impact case → asks user
# ---------------------------------------------------------------------------

def test_orange_flu_high_impact_asks_user(tmp_path):
    """The canonical case from the spec: hit counts vary >10× → ask."""
    # User picks the strongest-evidence slice (vitamin C + common cold).
    ui = MockUIAdapter([
        ("Vitamin C for common cold (strong evidence, 2,341+ papers)",
         '{"_use_component_focus": "true", "outcome": "common cold"}'),
    ])
    agent = _make_agent(
        ui=ui,
        pubmed_counts={
            ("Citrus sinensis", "Influenza"): 47,
            ("Ascorbic Acid", "Influenza"): 312,
            ("Citrus sinensis", "Common Cold"): 80,
            ("Ascorbic Acid", "Common Cold"): 2341,
            ("Citrus sinensis", "Respiratory"): 60,
            ("Ascorbic Acid", "Respiratory"): 1876,
        },
        resolver_concepts={
            "food": _orange(),
            "outcome": _flu(),
            "component": _vitamin_c(),
        },
        related={
            "broader": _resp_infections(),
            "sibling": _common_cold(),
            "__by_term__": {"common cold": _common_cold()},
        },
        tmp_log=tmp_path / "e.jsonl",
    )

    pico = PartialPICO(
        raw_claim="does orange prevent flu",
        food="orange",
        outcome="flu",
        component="vitamin C",
        ambiguous_slots=["population"],
    )
    locked = agent.elicit(pico)

    # The agent asked the landscape question — option text uses the
    # concept user_term verbatim ("vitamin C" lowercased), so do a
    # case-insensitive substring check.
    asked = [q["text"].lower() + " " + " ".join(q["options"]).lower() for q in ui.asked_questions]
    assert any("vitamin c for common cold" in s for s in asked)

    # The chosen slice swapped outcome to common cold.
    assert locked.outcome == "common cold"


def test_landscape_options_are_ranked_by_hit_count(tmp_path):
    captured = []

    class _CapturingUI:
        def ask(self, question):
            captured.append(question)
            return question["options"][0], question["option_values"][0]

    ui = _CapturingUI()
    agent = _make_agent(
        ui=ui,
        pubmed_counts={
            ("Citrus sinensis", "Influenza"): 47,
            ("Ascorbic Acid", "Influenza"): 312,
            ("Citrus sinensis", "Common Cold"): 80,
            ("Ascorbic Acid", "Common Cold"): 2341,
            ("Citrus sinensis", "Respiratory"): 60,
            ("Ascorbic Acid", "Respiratory"): 1876,
        },
        resolver_concepts={
            "food": _orange(),
            "outcome": _flu(),
            "component": _vitamin_c(),
        },
        related={
            "broader": _resp_infections(),
            "sibling": _common_cold(),
            "__by_term__": {"common cold": _common_cold()},
        },
        tmp_log=tmp_path / "e.jsonl",
    )

    pico = PartialPICO(
        raw_claim="x", food="orange", outcome="flu",
        component="vitamin C", population="adult",
    )
    agent.elicit(pico)

    # The first asked question (landscape) should have options sorted desc
    # by hit count — which means the highest-count slice appears first.
    landscape_q = captured[0]
    assert "Common Cold" in landscape_q["options"][0] or "common cold" in landscape_q["options"][0]


# ---------------------------------------------------------------------------
# Low-impact case → silent auto-pick
# ---------------------------------------------------------------------------

def test_low_impact_does_not_ask(tmp_path):
    """When hit counts are all roughly equal (<3× ratio), don't bother asking."""
    ui = MockUIAdapter([])  # would error if any question asked

    agent = _make_agent(
        ui=ui,
        pubmed_counts={
            "Citrus sinensis": 200,
            "Ascorbic Acid": 220,
            "Common Cold": 250,
            "Respiratory Tract Infections": 240,
        },
        resolver_concepts={
            "food": _orange(),
            "outcome": _flu(),
            "component": _vitamin_c(),
        },
        related={
            "broader": _resp_infections(),
            "sibling": _common_cold(),
        },
        tmp_log=tmp_path / "e.jsonl",
    )

    pico = PartialPICO(
        raw_claim="x", food="orange", outcome="flu",
        component="vitamin C", population="adult",
    )
    locked = agent.elicit(pico)

    # No questions were asked.
    assert ui.asked_questions == []
    # Still produced a locked PICO.
    assert locked.locked is True


# ---------------------------------------------------------------------------
# Insufficient evidence case → don't ask
# ---------------------------------------------------------------------------

def test_insufficient_evidence_does_not_ask(tmp_path):
    """If even the top slice has fewer than INSUFFICIENT_HITS, don't bother asking."""
    ui = MockUIAdapter([])

    agent = _make_agent(
        ui=ui,
        pubmed_counts={
            "Citrus sinensis": 2,
            "Ascorbic Acid": 1,
            "Common Cold": 0,
        },
        resolver_concepts={
            "food": _orange(),
            "outcome": _flu(),
            "component": _vitamin_c(),
        },
        related={"sibling": _common_cold()},
        tmp_log=tmp_path / "e.jsonl",
    )

    pico = PartialPICO(
        raw_claim="x", food="obscurefruit", outcome="flu",
        component="vitamin C", population="adult",
    )
    locked = agent.elicit(pico)

    assert ui.asked_questions == []
    assert locked.locked is True


# ---------------------------------------------------------------------------
# Probe budget enforced
# ---------------------------------------------------------------------------

def test_probe_budget_caps_pubmed_calls(tmp_path):
    ui = MockUIAdapter([
        ("opt 1", "{}"),
    ])

    agent = _make_agent(
        ui=ui,
        pubmed_counts={
            "Citrus sinensis": 1000,
            "Ascorbic Acid": 50,
            "Common Cold": 5,
        },
        resolver_concepts={
            "food": _orange(),
            "outcome": _flu(),
            "component": _vitamin_c(),
        },
        related={"broader": _resp_infections(), "sibling": _common_cold()},
        tmp_log=tmp_path / "e.jsonl",
    )
    agent.max_probes = 3   # tight budget

    pico = PartialPICO(
        raw_claim="x", food="orange", outcome="flu",
        component="vitamin C", population="adult",
    )
    agent.elicit(pico)

    # Even though many slices are available, only ``max_probes`` pubmed.count
    # calls should have happened.
    assert agent.pubmed.count.call_count <= 3


# ---------------------------------------------------------------------------
# Defaults applied when concepts can't be resolved
# ---------------------------------------------------------------------------

def test_lock_falls_back_to_default_population(tmp_path):
    ui = MockUIAdapter([])
    agent = _make_agent(
        ui=ui,
        pubmed_counts={"Citrus sinensis": 50},
        resolver_concepts={"food": _orange(), "outcome": _flu()},
        related={},
        tmp_log=tmp_path / "e.jsonl",
    )
    pico = PartialPICO(
        raw_claim="x", food="orange", outcome="flu",
        ambiguous_slots=["population"],
    )
    locked = agent.elicit(pico)
    assert locked.population == "healthy adults"
    assert "population" in locked.fallbacks_used


# ---------------------------------------------------------------------------
# Audit log records probes + chosen overrides
# ---------------------------------------------------------------------------

def test_audit_log_includes_probes_and_choice(tmp_path):
    import json

    ui = MockUIAdapter([
        ("Vitamin C for common cold (strong evidence, 2,341+ papers)",
         '{"_use_component_focus": "true", "outcome": "common cold"}'),
    ])
    log_file = tmp_path / "e.jsonl"
    agent = _make_agent(
        ui=ui,
        pubmed_counts={
            ("Citrus sinensis", "Influenza"): 47,
            ("Ascorbic Acid", "Influenza"): 312,
            ("Citrus sinensis", "Common Cold"): 80,
            ("Ascorbic Acid", "Common Cold"): 2341,
            ("Citrus sinensis", "Respiratory"): 60,
            ("Ascorbic Acid", "Respiratory"): 1876,
        },
        resolver_concepts={
            "food": _orange(),
            "outcome": _flu(),
            "component": _vitamin_c(),
        },
        related={
            "broader": _resp_infections(),
            "sibling": _common_cold(),
            "__by_term__": {"common cold": _common_cold()},
        },
        tmp_log=log_file,
    )

    pico = PartialPICO(
        raw_claim="does orange prevent flu",
        food="orange", outcome="flu", component="vitamin C",
        population="adult",
    )
    agent.elicit(pico)

    record = json.loads(log_file.read_text().strip().splitlines()[-1])
    assert record["elicitation_mode"] == "adaptive"
    assert "probes" in record
    assert len(record["probes"]) >= 2
    assert record["chosen_overrides"]["outcome"] == "common cold"
    # Probes ranked by count desc
    counts = [p["count"] for p in record["probes"]]
    assert counts == sorted(counts, reverse=True)
