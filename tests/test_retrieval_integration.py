"""Integration tests: real QueryBuilder + real ConceptResolver, mocked LLM/PubMed.

These tests exercise the full agent → tools → resolver → query builder
stack on canonical demo PICOs. The only things mocked are the external
I/O: the LLM provider (concept-resolution + agent tool calls) and
PubMed's HTTP client.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.extraction.llm_client import LLMClient
from src.retrieval.agent_llm import ScriptedAgentLLM, ToolCall
from src.retrieval.concept_query_builder import QueryBuilder
from src.retrieval.concept_resolver import ConceptResolver
from src.retrieval.retrieval_agent_new import RetrievalAgent
from src.retrieval.schemas import ESearchResult
from src.schemas import PartialPICO


# ---------------------------------------------------------------------------
# Shared fake infrastructure
# ---------------------------------------------------------------------------

def _resolver_llm_for(slot_to_resolution: dict[str, dict]) -> LLMClient:
    """Resolver LLM that returns a pre-baked resolution per call.

    Responses are consumed in order — each successive call to ``resolver.resolve``
    gets the next one. For parallel ``resolve_pico``, ordering is non-deterministic
    but tests above just check resolved concepts by slot key.
    """
    pending = list(slot_to_resolution.values())

    def provider(messages, response_schema, model, temperature):
        if not pending:
            raise AssertionError("resolver LLM exhausted")
        return json.dumps(pending.pop(0))

    return LLMClient(provider=provider, log_file="/tmp/test_retrieval_integration.jsonl")


def _mock_pubmed_with_plan(search_plan: dict[str, tuple[list[str], int]]):
    """PubMed double where count/esearch match the first query-substring key."""
    pubmed = MagicMock()

    def _match(query):
        for needle, (pmids, total) in search_plan.items():
            if needle in query:
                return pmids, total
        return [], 0

    def _esearch(query, max_results=100, sort="relevance"):
        pmids, total = _match(query)
        return ESearchResult(
            query=query, pmids=pmids, total_count=total,
            returned_count=len(pmids),
        )

    def _count(query):
        return _match(query)[1]

    def _fetch_details(pmids):
        return [
            {
                "pmid": p, "title": f"Paper {p}", "abstract": f"Abstract {p}",
                "pub_types": ["Journal Article"], "journal": "Journal",
                "year": 2024, "authors": ["Doe J"],
            }
            for p in pmids
        ]

    pubmed.esearch.side_effect = _esearch
    pubmed.count.side_effect = _count
    pubmed.fetch_details.side_effect = _fetch_details
    return pubmed


# ---------------------------------------------------------------------------
# Scenario 1: orange / flu — the canonical fix
# ---------------------------------------------------------------------------

def test_integration_orange_flu(tmp_path):
    resolver_llm = _resolver_llm_for({
        "food": {"primary_mesh": "Citrus sinensis", "alternative_mesh": ["Citrus"],
                 "tiab_synonyms": ["orange", "oranges"], "reasoning": "fruit"},
        "outcome": {"primary_mesh": "Influenza, Human", "alternative_mesh": [],
                    "tiab_synonyms": ["flu", "influenza"], "reasoning": ""},
        "component": {"primary_mesh": "Ascorbic Acid", "alternative_mesh": [],
                      "tiab_synonyms": ["vitamin C"], "reasoning": ""},
        "population": {"primary_mesh": "Adult", "alternative_mesh": [],
                       "tiab_synonyms": ["adult"], "reasoning": ""},
    })

    pubmed = _mock_pubmed_with_plan({
        # Agent-issued queries FIRST (they contain " AND " — more specific
        # patterns must match before the bare-MeSH validation entries).
        'Citrus sinensis"[MeSH Terms] AND': (["d1", "d2"], 4),                      # direct
        'Ascorbic Acid"[MeSH Terms] AND': ([f"v{i}" for i in range(28)], 340),       # mechanism
        # Concept-resolver validation calls (plain MeSH queries, no AND).
        '"Citrus sinensis"[MeSH Terms]': ([], 5000),
        '"Influenza, Human"[MeSH Terms]': ([], 90000),
        '"Ascorbic Acid"[MeSH Terms]': ([], 45000),
        '"Adult"[MeSH Terms]': ([], 1_000_000),
    })

    resolver = ConceptResolver(resolver_llm, pubmed)

    agent_llm = ScriptedAgentLLM([
        ToolCall("plan_query", {"slots": ["food", "outcome"]}),
        ToolCall("pubmed_count", {"query": "Citrus sinensis AND Influenza, Human"}),
        ToolCall("pubmed_search", {
            "query": '"Citrus sinensis"[MeSH Terms] AND "Influenza, Human"[MeSH Terms]',
            "rationale": "direct query",
        }),
        ToolCall("plan_query", {"slots": ["component", "outcome"]}),
        ToolCall("pubmed_search", {
            "query": '"Ascorbic Acid"[MeSH Terms] AND "Influenza, Human"[MeSH Terms]',
            "rationale": "mechanism query after direct was sparse",
        }),
        ToolCall("finish", {"rationale": "mechanism path found the real literature"}),
    ])

    agent = RetrievalAgent(
        llm=agent_llm,
        pubmed=pubmed,
        resolver=resolver,
        builder=QueryBuilder(),
        caers=None,
        log_file=str(tmp_path / "r.jsonl"),
        run_caers_in_parallel=False,
    )

    pico = PartialPICO(
        raw_claim="does orange prevent flu",
        food="orange",
        outcome="flu",
        component="vitamin C",
        population="adult",
    )
    result = agent.retrieve(pico)

    # --- Concepts resolved correctly ---
    assert "Citrus sinensis" in result.concept_resolutions["food"].mesh_terms
    assert "Influenza, Human" in result.concept_resolutions["outcome"].mesh_terms
    assert "Ascorbic Acid" in result.concept_resolutions["component"].mesh_terms

    # --- The critical regression check ---
    pmids = {p.pmid for p in result.papers}
    assert "v0" in pmids, "mechanism query must have surfaced vitamin C literature"
    assert len(result.papers) >= 15

    # --- Audit trail records both queries ---
    queries = [q.query_string for q in result.queries_executed]
    assert any("Citrus sinensis" in q for q in queries)
    assert any("Ascorbic Acid" in q for q in queries)


# ---------------------------------------------------------------------------
# Scenario 2: turmeric / inflammation
# ---------------------------------------------------------------------------

def test_integration_turmeric_inflammation(tmp_path):
    resolver_llm = _resolver_llm_for({
        "food": {"primary_mesh": "Curcuma", "alternative_mesh": ["Curcumin"],
                 "tiab_synonyms": ["turmeric", "curcumin"], "reasoning": ""},
        "outcome": {"primary_mesh": "Inflammation", "alternative_mesh": [],
                    "tiab_synonyms": ["inflammation"], "reasoning": ""},
        "population": {"primary_mesh": "Adult", "alternative_mesh": [],
                       "tiab_synonyms": ["adult"], "reasoning": ""},
    })
    pubmed = _mock_pubmed_with_plan({
        '"Curcuma"[MeSH Terms]': ([], 8000),
        '"Inflammation"[MeSH Terms]': ([], 500000),
        '"Adult"[MeSH Terms]': ([], 1_000_000),
        "Curcuma": ([f"t{i}" for i in range(32)], 400),
    })
    resolver = ConceptResolver(resolver_llm, pubmed)

    agent_llm = ScriptedAgentLLM([
        ToolCall("plan_query", {"slots": ["food", "outcome"]}),
        ToolCall("pubmed_search", {"query": "Curcuma AND Inflammation", "rationale": "direct"}),
        ToolCall("finish", {"rationale": "strong direct query"}),
    ])
    agent = RetrievalAgent(
        llm=agent_llm, pubmed=pubmed, resolver=resolver, builder=QueryBuilder(),
        caers=None, log_file=str(tmp_path / "r.jsonl"), run_caers_in_parallel=False,
    )

    pico = PartialPICO(
        raw_claim="does turmeric reduce inflammation",
        food="turmeric", outcome="inflammation", population="adult",
    )
    result = agent.retrieve(pico)

    assert "Curcuma" in result.concept_resolutions["food"].mesh_terms
    assert len(result.papers) >= 15


# ---------------------------------------------------------------------------
# Scenario 3: coffee / pregnancy
# ---------------------------------------------------------------------------

def test_integration_coffee_pregnancy(tmp_path):
    resolver_llm = _resolver_llm_for({
        "food": {"primary_mesh": "Coffee", "alternative_mesh": [],
                 "tiab_synonyms": ["coffee"], "reasoning": ""},
        "outcome": {"primary_mesh": "Pregnancy Outcome", "alternative_mesh": [],
                    "tiab_synonyms": ["pregnancy outcome"], "reasoning": ""},
        "component": {"primary_mesh": "Caffeine", "alternative_mesh": [],
                      "tiab_synonyms": ["caffeine"], "reasoning": ""},
        "population": {"primary_mesh": "Pregnant Women", "alternative_mesh": ["Pregnancy"],
                       "tiab_synonyms": ["pregnant"], "reasoning": ""},
    })
    pubmed = _mock_pubmed_with_plan({
        '"Coffee"[MeSH Terms]': ([], 12000),
        '"Pregnancy Outcome"[MeSH Terms]': ([], 80000),
        '"Caffeine"[MeSH Terms]': ([], 40000),
        '"Pregnant Women"[MeSH Terms]': ([], 120000),
        "Coffee": ([f"c{i}" for i in range(22)], 180),
    })
    resolver = ConceptResolver(resolver_llm, pubmed)

    agent_llm = ScriptedAgentLLM([
        ToolCall("plan_query", {"slots": ["food", "outcome"]}),
        ToolCall("pubmed_search", {"query": "Coffee AND Pregnancy", "rationale": "direct"}),
        ToolCall("finish", {"rationale": "direct query productive"}),
    ])
    agent = RetrievalAgent(
        llm=agent_llm, pubmed=pubmed, resolver=resolver, builder=QueryBuilder(),
        caers=None, log_file=str(tmp_path / "r.jsonl"), run_caers_in_parallel=False,
    )
    pico = PartialPICO(
        raw_claim="is coffee bad during pregnancy",
        food="coffee", outcome="pregnancy outcome",
        component="caffeine", population="pregnant",
    )
    result = agent.retrieve(pico)
    assert result.concept_resolutions["component"].mesh_terms == ["Caffeine"]
    assert len(result.papers) >= 15


# ---------------------------------------------------------------------------
# Scenario 4: red meat / cancer
# ---------------------------------------------------------------------------

def test_integration_red_meat_cancer(tmp_path):
    resolver_llm = _resolver_llm_for({
        "food": {"primary_mesh": "Red Meat", "alternative_mesh": ["Meat"],
                 "tiab_synonyms": ["red meat", "beef"], "reasoning": ""},
        "outcome": {"primary_mesh": "Neoplasms", "alternative_mesh": ["Colorectal Neoplasms"],
                    "tiab_synonyms": ["cancer"], "reasoning": ""},
        "population": {"primary_mesh": "Adult", "alternative_mesh": [],
                       "tiab_synonyms": ["adult"], "reasoning": ""},
    })
    pubmed = _mock_pubmed_with_plan({
        '"Red Meat"[MeSH Terms]': ([], 4000),
        '"Neoplasms"[MeSH Terms]': ([], 3_000_000),
        '"Adult"[MeSH Terms]': ([], 1_000_000),
        "Red Meat": ([f"r{i}" for i in range(40)], 600),
    })
    resolver = ConceptResolver(resolver_llm, pubmed)

    agent_llm = ScriptedAgentLLM([
        ToolCall("plan_query", {"slots": ["food", "outcome"]}),
        ToolCall("pubmed_search", {"query": "Red Meat AND Neoplasms", "rationale": "direct"}),
        ToolCall("finish", {"rationale": "done"}),
    ])
    agent = RetrievalAgent(
        llm=agent_llm, pubmed=pubmed, resolver=resolver, builder=QueryBuilder(),
        caers=None, log_file=str(tmp_path / "r.jsonl"), run_caers_in_parallel=False,
    )
    pico = PartialPICO(
        raw_claim="does red meat cause cancer",
        food="red meat", outcome="cancer", population="adult",
    )
    result = agent.retrieve(pico)
    assert "Red Meat" in result.concept_resolutions["food"].mesh_terms
    assert len(result.papers) >= 15


# ---------------------------------------------------------------------------
# Scenario 5: vitamin D / COVID — tests min_year handling
# ---------------------------------------------------------------------------

def test_integration_vitamin_d_covid_min_year(tmp_path):
    resolver_llm = _resolver_llm_for({
        "food": {"primary_mesh": "Vitamin D", "alternative_mesh": ["Cholecalciferol"],
                 "tiab_synonyms": ["vitamin D"], "reasoning": ""},
        "outcome": {"primary_mesh": "COVID-19", "alternative_mesh": [],
                    "tiab_synonyms": ["COVID-19", "SARS-CoV-2"], "reasoning": ""},
        "population": {"primary_mesh": "Adult", "alternative_mesh": [],
                       "tiab_synonyms": ["adult"], "reasoning": ""},
    })
    pubmed = _mock_pubmed_with_plan({
        '"Vitamin D"[MeSH Terms]': ([], 95000),
        '"COVID-19"[MeSH Terms]': ([], 400000),
        '"Adult"[MeSH Terms]': ([], 1_000_000),
        "Vitamin D": ([f"vd{i}" for i in range(25)], 300),
    })
    resolver = ConceptResolver(resolver_llm, pubmed)

    agent_llm = ScriptedAgentLLM([
        ToolCall("plan_query", {"slots": ["food", "outcome"], "min_year": 2020}),
        ToolCall("pubmed_search", {
            "query": "Vitamin D AND COVID-19",
            "rationale": "date-gated direct",
        }),
        ToolCall("finish", {"rationale": "done"}),
    ])
    agent = RetrievalAgent(
        llm=agent_llm, pubmed=pubmed, resolver=resolver, builder=QueryBuilder(),
        caers=None, log_file=str(tmp_path / "r.jsonl"), run_caers_in_parallel=False,
    )
    pico = PartialPICO(
        raw_claim="does vitamin D prevent covid",
        food="vitamin D", outcome="COVID-19", population="adult",
    )
    result = agent.retrieve(pico)
    assert len(result.papers) >= 15


# ---------------------------------------------------------------------------
# Generic regression: no mechanism query issued when component is missing
# ---------------------------------------------------------------------------

def test_mechanism_query_skipped_when_no_component(tmp_path):
    resolver_llm = _resolver_llm_for({
        "food": {"primary_mesh": "Curcuma", "alternative_mesh": [],
                 "tiab_synonyms": ["turmeric"], "reasoning": ""},
        "outcome": {"primary_mesh": "Inflammation", "alternative_mesh": [],
                    "tiab_synonyms": ["inflammation"], "reasoning": ""},
    })
    pubmed = _mock_pubmed_with_plan({
        '"Curcuma"[MeSH Terms]': ([], 8000),
        '"Inflammation"[MeSH Terms]': ([], 500000),
        "Curcuma": ([f"t{i}" for i in range(22)], 220),
    })
    resolver = ConceptResolver(resolver_llm, pubmed)

    agent_llm = ScriptedAgentLLM([
        ToolCall("plan_query", {"slots": ["component", "outcome"]}),   # nothing to build
        ToolCall("plan_query", {"slots": ["food", "outcome"]}),
        ToolCall("pubmed_search", {"query": "Curcuma AND Inflammation", "rationale": "fallback"}),
        ToolCall("finish", {"rationale": "done"}),
    ])
    agent = RetrievalAgent(
        llm=agent_llm, pubmed=pubmed, resolver=resolver, builder=QueryBuilder(),
        caers=None, log_file=str(tmp_path / "r.jsonl"), run_caers_in_parallel=False,
    )
    pico = PartialPICO(raw_claim="x", food="turmeric", outcome="inflammation")
    result = agent.retrieve(pico)
    # First plan_query returned an error in result (no component), agent continued.
    assert len(result.papers) >= 15
