"""Tests for the new RetrievalAgent — retrieval spec Tasks 6, 7, 9, 10.

Uses ScriptedAgentLLM to drive the loop deterministically. Real Gemini
is NOT called; the live smoke test lives in a separate file and is
gated on ``RUN_LIVE_TESTS=1``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.retrieval.agent_llm import ScriptedAgentLLM, Stop, ToolCall
from src.retrieval.query_builder import QueryBuilder
from src.retrieval.retrieval_agent import RetrievalAgent
from src.retrieval.schemas import (
    CAERSReport,
    Concept,
    ESearchResult,
)
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


def _mock_resolver(pico_concepts: dict[str, Concept]):
    resolver = MagicMock()
    resolver.resolve_pico.return_value = dict(pico_concepts)
    related_default = Concept(
        user_term="related",
        mesh_terms=["Common Cold"],
        tiab_synonyms=["common cold"],
        validated=True,
    )
    resolver.resolve.return_value = related_default
    resolver.resolve_related.return_value = related_default
    return resolver


def _mock_pubmed(search_results: dict[str, tuple[list[str], int]] = None):
    """pubmed double. search_results maps query-substring → (pmids, total_count)."""
    pubmed = MagicMock()
    search_results = search_results or {}

    def _esearch(query, max_results=100, sort="relevance"):
        for needle, (pmids, total) in search_results.items():
            if needle in query:
                return ESearchResult(
                    query=query, pmids=pmids, total_count=total,
                    returned_count=len(pmids),
                )
        return ESearchResult(
            query=query, pmids=[], total_count=0, returned_count=0
        )

    def _count(query):
        for needle, (pmids, total) in search_results.items():
            if needle in query:
                return total
        return 0

    def _fetch_details(pmids):
        return [
            {
                "pmid": p,
                "title": f"Paper {p}",
                "abstract": f"Abstract for {p}",
                "pub_types": ["Journal Article"],
                "journal": "Journal",
                "year": 2024,
                "authors": ["Doe J"],
            }
            for p in pmids
        ]

    pubmed.esearch.side_effect = _esearch
    pubmed.count.side_effect = _count
    pubmed.fetch_details.side_effect = _fetch_details
    return pubmed


def _make_agent(*, llm=None, pubmed=None, resolver=None, caers=None, tmp_log=None):
    return RetrievalAgent(
        llm=llm or ScriptedAgentLLM([]),
        pubmed=pubmed or _mock_pubmed(),
        resolver=resolver or _mock_resolver({}),
        builder=QueryBuilder(),
        caers=caers,
        log_file=str(tmp_log) if tmp_log else "/tmp/test_retrieval.jsonl",
        run_caers_in_parallel=False,  # simpler to reason about in tests
    )


# ---------------------------------------------------------------------------
# Happy path: direct query, few results, finish
# ---------------------------------------------------------------------------

def test_agent_runs_direct_query_and_finishes(tmp_path):
    """Simple flow: plan, count, search, finish (with below_threshold bypass)."""
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    pubmed = _mock_pubmed({"Citrus sinensis": (["111", "222", "333"], 300)})

    scripted = ScriptedAgentLLM([
        ToolCall("plan_query", {"slots": ["food", "outcome"]}),
        ToolCall("pubmed_count", {"query": "<from plan>"}),
        ToolCall("pubmed_search", {"query": "Citrus sinensis", "rationale": "direct"}),
        # Tiny claim, single productive query — use the documented
        # below_threshold bypass so finish is accepted.
        ToolCall("finish", {"rationale": "tiny evidence base; below_threshold"}),
    ])
    agent = _make_agent(llm=scripted, pubmed=pubmed, resolver=resolver, tmp_log=tmp_path / "r.jsonl")

    pico = PartialPICO(
        raw_claim="does orange prevent flu",
        food="orange",
        outcome="flu",
        population="healthy_adults",
    )
    result = agent.retrieve(pico)

    assert len(result.papers) == 3
    assert {p.pmid for p in result.papers} == {"111", "222", "333"}
    assert "below_threshold" in result.finish_rationale
    assert result.total_iterations == 4


def test_agent_source_query_attached_to_papers(tmp_path):
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    pubmed = _mock_pubmed({"Citrus sinensis": (["111"], 10)})
    scripted = ScriptedAgentLLM([
        ToolCall("pubmed_search", {"query": "Citrus sinensis AND flu", "rationale": "direct"}),
        ToolCall("finish", {"rationale": "done"}),
    ])
    agent = _make_agent(llm=scripted, pubmed=pubmed, resolver=resolver, tmp_log=tmp_path / "r.jsonl")

    pico = PartialPICO(raw_claim="x", food="orange", outcome="flu")
    result = agent.retrieve(pico)
    assert result.papers[0].source_query == "Citrus sinensis AND flu"


# ---------------------------------------------------------------------------
# Orange/flu regression: mechanism query via component
# ---------------------------------------------------------------------------

def test_orange_flu_mechanism_query_finds_vitamin_c_literature(tmp_path):
    """The canonical retrieval-spec scenario: direct query flops, mechanism saves it."""
    concepts = {"food": _orange(), "outcome": _flu(), "component": _vitamin_c()}
    resolver = _mock_resolver(concepts)

    # Direct query: only 2 PMIDs. Mechanism query on Ascorbic Acid: 28 PMIDs.
    pubmed = _mock_pubmed({
        "Citrus sinensis": (["d1", "d2"], 4),
        "Ascorbic Acid": ([f"v{i}" for i in range(28)], 340),
    })

    scripted = ScriptedAgentLLM([
        ToolCall("pubmed_count", {"query": "Citrus sinensis"}),
        ToolCall("pubmed_search", {"query": "Citrus sinensis", "rationale": "direct"}),
        ToolCall("pubmed_count", {"query": "Ascorbic Acid"}),
        ToolCall("pubmed_search", {"query": "Ascorbic Acid", "rationale": "mechanism"}),
        ToolCall("finish", {"rationale": "mechanism query rescued the retrieval"}),
    ])
    agent = _make_agent(llm=scripted, pubmed=pubmed, resolver=resolver, tmp_log=tmp_path / "r.jsonl")

    pico = PartialPICO(
        raw_claim="does orange prevent flu",
        food="orange",
        outcome="flu",
        component="vitamin C",
        population="healthy_adults",
    )
    result = agent.retrieve(pico)

    # Both direct and mechanism PMIDs should end up in the final set.
    pmids = {p.pmid for p in result.papers}
    assert "d1" in pmids
    assert "v0" in pmids
    assert len(result.papers) == 30
    # Both queries were actually executed.
    assert len(result.queries_executed) == 2


# ---------------------------------------------------------------------------
# Semantic relaxation: get_related_concept + plan_query
# ---------------------------------------------------------------------------

def test_agent_uses_related_concept_when_direct_is_sparse(tmp_path):
    concepts = {"food": _orange(), "outcome": _flu()}
    resolver = _mock_resolver(concepts)
    # direct → sparse (1 pmid, not productive); common cold → productive (18 new)
    pubmed = _mock_pubmed({
        "Citrus sinensis": (["d1"], 1),
        "Common Cold": ([f"c{i}" for i in range(18)], 220),
    })

    scripted = ScriptedAgentLLM([
        # First query is unproductive (1 new pmid < 5 threshold).
        ToolCall("pubmed_search", {"query": "Citrus sinensis", "rationale": "direct"}),
        ToolCall("get_related_concept", {"slot_name": "outcome", "direction": "sibling"}),
        # Second query is productive (18 new pmids).
        ToolCall("pubmed_search", {"query": "Common Cold", "rationale": "related outcome"}),
        # Still only 1 productive query — use below_threshold bypass.
        ToolCall("finish", {"rationale": "one productive path only; below_threshold if stricter"}),
    ])
    agent = _make_agent(llm=scripted, pubmed=pubmed, resolver=resolver, tmp_log=tmp_path / "r.jsonl")

    pico = PartialPICO(raw_claim="x", food="orange", outcome="flu")
    result = agent.retrieve(pico)

    pmids = {p.pmid for p in result.papers}
    assert "d1" in pmids
    assert "c0" in pmids
    # related_outcome got stored.
    assert "related_outcome" in result.concept_resolutions


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------

def test_agent_stops_at_max_iterations(tmp_path):
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    pubmed = _mock_pubmed({"Citrus sinensis": (["1"], 1)})

    # 20 identical tool calls — agent should hard-stop at max_iterations=8.
    scripted = ScriptedAgentLLM([
        ToolCall("pubmed_count", {"query": "Citrus sinensis"}) for _ in range(20)
    ])
    agent = _make_agent(llm=scripted, pubmed=pubmed, resolver=resolver, tmp_log=tmp_path / "r.jsonl")

    pico = PartialPICO(raw_claim="x", food="orange", outcome="flu")
    result = agent.retrieve(pico)

    assert result.total_iterations == 8
    assert result.budget_exhausted is True
    assert any("max_iterations" in n for n in result.retrieval_notes)


def test_agent_handles_llm_stop_without_finish(tmp_path):
    """If the LLM quits without calling finish, the agent records it and exits cleanly."""
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    scripted = ScriptedAgentLLM([Stop(text="I'm done thinking")])
    agent = _make_agent(llm=scripted, resolver=resolver, tmp_log=tmp_path / "r.jsonl")

    pico = PartialPICO(raw_claim="x", food="orange", outcome="flu")
    result = agent.retrieve(pico)

    assert result.total_iterations == 0
    assert any("LLM stopped without finish" in n for n in result.retrieval_notes)


# ---------------------------------------------------------------------------
# CAERS parallel track (Task 7)
# ---------------------------------------------------------------------------

def test_caers_reports_attached_when_client_provided(tmp_path):
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    pubmed = _mock_pubmed({"Citrus sinensis": (["1"], 1)})
    caers = MagicMock()
    caers.search_by_product.return_value = [
        CAERSReport(
            report_id="99",
            date="2023-01-01",
            product_name="Orange Juice",
            industry_name="Beverages",
            reactions=["Nausea"],
            outcomes=[],
        )
    ]
    scripted = ScriptedAgentLLM([
        ToolCall("pubmed_search", {"query": "Citrus sinensis", "rationale": "x"}),
        ToolCall("finish", {"rationale": "done"}),
    ])
    agent = _make_agent(
        llm=scripted, pubmed=pubmed, resolver=resolver, caers=caers,
        tmp_log=tmp_path / "r.jsonl",
    )

    pico = PartialPICO(raw_claim="x", food="orange", outcome="flu")
    result = agent.retrieve(pico)

    assert len(result.caers_reports) == 1
    caers.search_by_product.assert_called_once_with("orange", limit=50)


def test_caers_failure_does_not_break_pubmed_retrieval(tmp_path):
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    pubmed = _mock_pubmed({"Citrus sinensis": (["1"], 1)})
    caers = MagicMock()
    caers.search_by_product.side_effect = RuntimeError("openFDA down")
    scripted = ScriptedAgentLLM([
        ToolCall("pubmed_search", {"query": "Citrus sinensis", "rationale": "x"}),
        ToolCall("finish", {"rationale": "done"}),
    ])
    agent = _make_agent(
        llm=scripted, pubmed=pubmed, resolver=resolver, caers=caers,
        tmp_log=tmp_path / "r.jsonl",
    )
    pico = PartialPICO(raw_claim="x", food="orange", outcome="flu")
    result = agent.retrieve(pico)

    assert len(result.papers) == 1
    assert result.caers_reports == []


def test_caers_not_called_when_client_is_none(tmp_path):
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    pubmed = _mock_pubmed({"Citrus sinensis": (["1"], 1)})
    scripted = ScriptedAgentLLM([
        ToolCall("pubmed_search", {"query": "Citrus sinensis", "rationale": "x"}),
        ToolCall("finish", {"rationale": "done"}),
    ])
    agent = _make_agent(
        llm=scripted, pubmed=pubmed, resolver=resolver, caers=None,
        tmp_log=tmp_path / "r.jsonl",
    )
    pico = PartialPICO(raw_claim="x", food="orange", outcome="flu")
    result = agent.retrieve(pico)
    assert result.caers_reports == []


# ---------------------------------------------------------------------------
# Audit log (Task 9)
# ---------------------------------------------------------------------------

def test_audit_log_written_to_jsonl(tmp_path):
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    pubmed = _mock_pubmed({"Citrus sinensis": (["1", "2"], 2)})
    scripted = ScriptedAgentLLM([
        ToolCall("pubmed_count", {"query": "x"}),
        ToolCall("pubmed_search", {"query": "Citrus sinensis", "rationale": "x"}),
        # Only 0–1 productive queries (2 new pmids < threshold). Use bypass.
        ToolCall("finish", {"rationale": "small set — below_threshold"}),
    ])
    log_file = tmp_path / "r.jsonl"
    agent = _make_agent(llm=scripted, pubmed=pubmed, resolver=resolver, tmp_log=log_file)

    pico = PartialPICO(raw_claim="x", food="orange", outcome="flu")
    agent.retrieve(pico)

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    for field in (
        "timestamp",
        "raw_claim",
        "locked_pico",
        "concepts_resolved",
        "agent_iterations",
        "tool_calls",
        "queries_executed",
        "final_paper_count",
        "caers_report_count",
        "budget_exhausted",
        "finish_rationale",
    ):
        assert field in record
    assert record["final_paper_count"] == 2
    assert record["agent_iterations"] == 3
    assert "below_threshold" in record["finish_rationale"]
    # Each tool call should appear in the log.
    logged_names = [tc["tool"] for tc in record["tool_calls"]]
    assert logged_names == ["pubmed_count", "pubmed_search", "finish"]


def test_audit_log_appends_on_successive_runs(tmp_path):
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    pubmed = _mock_pubmed({"Citrus sinensis": (["1"], 1)})
    log_file = tmp_path / "r.jsonl"

    for _ in range(3):
        scripted = ScriptedAgentLLM([
            ToolCall("pubmed_search", {"query": "Citrus sinensis", "rationale": "x"}),
            ToolCall("finish", {"rationale": "done"}),
        ])
        agent = _make_agent(llm=scripted, pubmed=pubmed, resolver=resolver, tmp_log=log_file)
        agent.retrieve(PartialPICO(raw_claim="x", food="orange", outcome="flu"))

    assert len(log_file.read_text().strip().splitlines()) == 3


# ---------------------------------------------------------------------------
# Tool-call logging integrity
# ---------------------------------------------------------------------------

def test_every_tool_call_appears_in_log(tmp_path):
    resolver = _mock_resolver({"food": _orange(), "outcome": _flu()})
    pubmed = _mock_pubmed({"Citrus sinensis": (["1"], 1)})
    actions = [
        ToolCall("pubmed_count", {"query": "a"}),
        ToolCall("pubmed_count", {"query": "b"}),
        ToolCall("plan_query", {"slots": ["food", "outcome"]}),
        ToolCall("pubmed_search", {"query": "Citrus sinensis", "rationale": "x"}),
        ToolCall("finish", {"rationale": "done"}),
    ]
    scripted = ScriptedAgentLLM(list(actions))
    log_file = tmp_path / "r.jsonl"
    agent = _make_agent(llm=scripted, pubmed=pubmed, resolver=resolver, tmp_log=log_file)

    agent.retrieve(PartialPICO(raw_claim="x", food="orange", outcome="flu"))

    record = json.loads(log_file.read_text().strip().splitlines()[-1])
    names = [tc["tool"] for tc in record["tool_calls"]]
    assert names == [a.name for a in actions]
