"""Tests for RetrievalTools — retrieval spec Task 5."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.retrieval.agent_state import AgentState
from src.retrieval.query_builder import QueryBuilder
from src.retrieval.retrieval_tools import TOOL_DECLARATIONS, RetrievalTools
from src.retrieval.schemas import Concept, ESearchResult
from src.schemas import PartialPICO


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _orange() -> Concept:
    return Concept(
        user_term="orange",
        mesh_terms=["Citrus sinensis"],
        tiab_synonyms=["orange", "oranges"],
        validated=True,
    )


def _flu() -> Concept:
    return Concept(
        user_term="flu",
        mesh_terms=["Influenza, Human"],
        tiab_synonyms=["influenza", "flu"],
        validated=True,
    )


def _vitamin_c() -> Concept:
    return Concept(
        user_term="vitamin C",
        mesh_terms=["Ascorbic Acid"],
        tiab_synonyms=["vitamin C"],
        validated=True,
    )


def _make(concepts: dict) -> tuple[RetrievalTools, MagicMock, AgentState]:
    pubmed = MagicMock()
    resolver = MagicMock()
    state = AgentState(
        locked_pico=PartialPICO(raw_claim="test", food="orange", outcome="flu"),
        concepts=dict(concepts),
    )
    tools = RetrievalTools(pubmed, resolver, QueryBuilder(), state)
    return tools, pubmed, state


# ---------------------------------------------------------------------------
# pubmed_count
# ---------------------------------------------------------------------------

def test_pubmed_count_returns_count_and_query():
    tools, pubmed, state = _make({"food": _orange(), "outcome": _flu()})
    pubmed.count.return_value = 423

    result = tools.dispatch("pubmed_count", {"query": "x"})

    assert result == {"count": 423, "query": "x"}
    assert len(state.tool_call_log) == 1
    assert state.tool_call_log[0]["tool"] == "pubmed_count"


# ---------------------------------------------------------------------------
# pubmed_search
# ---------------------------------------------------------------------------

def test_pubmed_search_accumulates_pmids_and_records_query():
    tools, pubmed, state = _make({"food": _orange(), "outcome": _flu()})
    pubmed.esearch.return_value = ESearchResult(
        query="q",
        pmids=["111", "222"],
        total_count=500,
        returned_count=2,
    )
    pubmed.fetch_details.return_value = [
        {"pmid": "111", "title": "A", "journal": "J", "year": 2024, "pub_types": ["RCT"]},
        {"pmid": "222", "title": "B", "journal": "J", "year": 2023, "pub_types": []},
    ]

    result = tools.dispatch(
        "pubmed_search", {"query": "q", "max_results": 2, "rationale": "test"}
    )

    assert result["pmids"] == ["111", "222"]
    assert result["total_count"] == 500
    assert result["new_pmids_added"] == 2
    assert [p["pmid"] for p in result["papers"]] == ["111", "222"]
    assert state.accumulated_pmids == {"111", "222"}
    assert state.pmid_source["111"] == "q"
    assert len(state.executed_queries) == 1
    assert state.executed_queries[0].query_string == "q"
    assert state.executed_queries[0].rationale == "test"


def test_pubmed_search_counts_only_new_pmids_as_added():
    tools, pubmed, state = _make({"food": _orange(), "outcome": _flu()})
    state.accumulated_pmids = {"111"}   # pretend we already had 111

    pubmed.esearch.return_value = ESearchResult(
        query="q", pmids=["111", "222"], total_count=2, returned_count=2
    )
    pubmed.fetch_details.return_value = []

    result = tools.dispatch("pubmed_search", {"query": "q"})
    assert result["new_pmids_added"] == 1    # only 222 is new


def test_pubmed_search_empty_result_still_records_query():
    tools, pubmed, state = _make({"food": _orange(), "outcome": _flu()})
    pubmed.esearch.return_value = ESearchResult(
        query="q", pmids=[], total_count=0, returned_count=0
    )

    result = tools.dispatch("pubmed_search", {"query": "q"})
    assert result["pmids"] == []
    assert len(state.executed_queries) == 1
    # fetch_details must NOT be called for an empty pmid list
    pubmed.fetch_details.assert_not_called()


# ---------------------------------------------------------------------------
# plan_query
# ---------------------------------------------------------------------------

def test_plan_query_direct_food_outcome():
    tools, _, state = _make({"food": _orange(), "outcome": _flu()})
    result = tools.dispatch("plan_query", {"slots": ["food", "outcome"]})

    assert "query" in result
    assert result["strategy"] == "direct"
    assert '"Citrus sinensis"[MeSH Terms]' in result["query"]
    assert '"Influenza, Human"[MeSH Terms]' in result["query"]


def test_plan_query_mechanism_component_outcome():
    tools, _, state = _make({
        "food": _orange(),
        "outcome": _flu(),
        "component": _vitamin_c(),
    })
    result = tools.dispatch(
        "plan_query", {"slots": ["component", "outcome"]}
    )

    assert result["strategy"] == "mechanism"
    assert '"Ascorbic Acid"[MeSH Terms]' in result["query"]
    assert '"Citrus sinensis"[MeSH Terms]' not in result["query"]


def test_plan_query_related_outcome_aliases_to_outcome_axis():
    common_cold = Concept(
        user_term="common cold",
        mesh_terms=["Common Cold"],
        tiab_synonyms=["common cold"],
        validated=True,
    )
    tools, _, state = _make({
        "food": _orange(),
        "outcome": _flu(),
        "related_outcome": common_cold,
    })
    result = tools.dispatch(
        "plan_query", {"slots": ["food", "related_outcome"]}
    )

    # The original outcome must NOT appear; only the related one.
    assert '"Common Cold"[MeSH Terms]' in result["query"]
    assert '"Influenza, Human"[MeSH Terms]' not in result["query"]


def test_plan_query_applies_study_tiers():
    tools, _, _ = _make({"food": _orange(), "outcome": _flu()})
    result = tools.dispatch(
        "plan_query", {"slots": ["food", "outcome"], "study_tiers": [1, 2]}
    )

    assert '"systematic review"[Publication Type]' in result["query"]
    assert '"randomized controlled trial"[Publication Type]' in result["query"]


def test_plan_query_with_unknown_slot_silently_skips():
    tools, _, _ = _make({"food": _orange(), "outcome": _flu()})
    result = tools.dispatch(
        "plan_query", {"slots": ["food", "outcome", "nonexistent"]}
    )
    # Should still build the direct query from the known slots.
    assert "query" in result
    assert result["strategy"] == "direct"


def test_plan_query_empty_slots_returns_error():
    tools, _, _ = _make({})
    result = tools.dispatch("plan_query", {"slots": []})
    assert "error" in result


# ---------------------------------------------------------------------------
# get_related_concept
# ---------------------------------------------------------------------------

def test_get_related_concept_stores_under_related_key():
    tools, _, state = _make({"outcome": _flu()})
    common_cold = Concept(
        user_term="common cold",
        mesh_terms=["Common Cold"],
        tiab_synonyms=["common cold"],
        validated=True,
    )
    # ``get_related_concept`` now calls the dedicated resolve_related method.
    tools.resolver.resolve_related.return_value = common_cold

    result = tools.dispatch(
        "get_related_concept",
        {"slot_name": "outcome", "direction": "sibling"},
    )

    assert result["stored_as"] == "related_outcome"
    assert state.concepts["related_outcome"].mesh_terms == ["Common Cold"]


def test_get_related_concept_errors_when_slot_absent():
    tools, _, _ = _make({})
    result = tools.dispatch(
        "get_related_concept",
        {"slot_name": "outcome"},
    )
    assert "error" in result


def test_get_related_concept_caps_at_two_per_run():
    tools, _, state = _make({"outcome": _flu()})
    related = Concept(
        user_term="x", mesh_terms=["X"], tiab_synonyms=["x"], validated=True
    )
    tools.resolver.resolve_related.return_value = related

    # Two different directions so the duplicate-call guard doesn't interfere.
    tools.dispatch("get_related_concept", {"slot_name": "outcome", "direction": "broader"})
    tools.dispatch("get_related_concept", {"slot_name": "outcome", "direction": "sibling"})
    third = tools.dispatch("get_related_concept", {"slot_name": "outcome", "direction": "mechanism"})

    assert "error" in third
    assert "max 2" in third["error"]


# ---------------------------------------------------------------------------
# fetch_abstracts
# ---------------------------------------------------------------------------

def test_fetch_abstracts_returns_full_records():
    tools, pubmed, _ = _make({})
    pubmed.fetch_details.return_value = [
        {"pmid": "1", "title": "T", "abstract": "A", "pub_types": [], "year": 2024},
    ]
    result = tools.dispatch("fetch_abstracts", {"pmids": ["1"]})
    assert result["papers"][0]["abstract"] == "A"


# ---------------------------------------------------------------------------
# finish
# ---------------------------------------------------------------------------

def test_finish_marks_state_finished_once_productive_threshold_met():
    tools, _, state = _make({})
    state.productive_queries = 2  # satisfy the new stopping rule
    result = tools.dispatch(
        "finish", {"rationale": "enough evidence", "chosen_pmids": ["1", "2"]}
    )

    assert state.finished is True
    assert state.finish_rationale == "enough evidence"
    assert state.accumulated_pmids == {"1", "2"}
    assert result["ok"] is True


def test_finish_blocked_before_two_productive_queries():
    tools, _, state = _make({})
    # productive_queries defaults to 0
    result = tools.dispatch("finish", {"rationale": "done"})

    assert state.finished is False
    assert "error" in result
    assert "productive queries" in result["error"]


def test_finish_bypass_allowed_on_below_threshold_rationale():
    """When evidence genuinely doesn't exist, the agent needs an escape hatch."""
    tools, _, state = _make({})
    # Still 0 productive queries, but bypass token present.
    result = tools.dispatch(
        "finish",
        {"rationale": "no results anywhere — below_threshold, giving up"},
    )

    assert state.finished is True
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# dispatch error handling
# ---------------------------------------------------------------------------

def test_dispatch_unknown_tool_returns_error():
    tools, _, state = _make({})
    result = tools.dispatch("not_a_tool", {})
    assert "error" in result
    assert "unknown tool" in result["error"]
    # Still logged.
    assert state.tool_call_log[-1]["tool"] == "not_a_tool"


def test_dispatch_bad_args_returns_error():
    tools, _, _ = _make({})
    result = tools.dispatch("pubmed_count", {"wrong_arg": "x"})
    assert "error" in result


def test_dispatch_private_method_not_callable_as_tool():
    """Methods not flagged with ``_is_tool = True`` must be unreachable."""
    tools, _, _ = _make({})
    result = tools.dispatch("_summarise", {"anything": 1})
    assert "error" in result


def test_every_tool_declaration_matches_a_real_method():
    """Every entry in TOOL_DECLARATIONS must map to a real tool method."""
    tools, _, _ = _make({})
    for decl in TOOL_DECLARATIONS:
        method = getattr(tools, decl["name"], None)
        assert method is not None, f"missing method for tool {decl['name']}"
        assert getattr(method, "_is_tool", False), (
            f"method {decl['name']} is not marked _is_tool"
        )


def test_all_tool_calls_are_logged():
    tools, pubmed, state = _make({"food": _orange(), "outcome": _flu()})
    pubmed.count.return_value = 10
    tools.dispatch("pubmed_count", {"query": "x"})
    tools.dispatch("plan_query", {"slots": ["food", "outcome"]})

    logged_tools = [e["tool"] for e in state.tool_call_log]
    assert logged_tools == ["pubmed_count", "plan_query"]
