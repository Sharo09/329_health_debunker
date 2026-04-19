"""Live end-to-end smoke test for Station 3 — retrieval spec Task 11.

Skipped by default. Runs ONLY when ``RUN_LIVE_TESTS=1`` is set in the
environment. Hits real Gemini (needs ``GOOGLE_API_KEY``) and real PubMed
(optionally ``NCBI_API_KEY`` / ``PUBMED_API_KEY``).

Do NOT run in CI.
"""

from __future__ import annotations

import os

import pytest

from src.retrieval.agent_llm import GeminiAgentLLM
from src.retrieval.retrieval_agent import RetrievalAgent
from src.schemas import PartialPICO


_RUN = bool(os.getenv("RUN_LIVE_TESTS"))


pytestmark = pytest.mark.skipif(
    not _RUN,
    reason="live LLM + live PubMed test — set RUN_LIVE_TESTS=1 to run",
)


def test_live_orange_flu_retrieves_real_papers(tmp_path):
    """The canonical claim. Expect ≥15 papers with at least one RCT / SR / meta-analysis."""
    model = os.getenv("LIVE_LLM_MODEL", "gemini-2.5-flash")
    agent = RetrievalAgent(
        llm=GeminiAgentLLM(model=model),
        log_file=str(tmp_path / "r.jsonl"),
    )

    pico = PartialPICO(
        raw_claim="does orange prevent flu",
        food="orange",
        outcome="flu",
        component="vitamin C",           # Station 1 is expected to have inferred this
        population="healthy_adults",
        form="dietary",
    )
    result = agent.retrieve(pico)

    # --- Concept-resolution sanity ---
    # "orange" must resolve to the fruit, not the colour.
    food_mesh = result.concept_resolutions["food"].mesh_terms
    assert any("Citrus" in m for m in food_mesh), (
        f"expected a Citrus* MeSH for orange, got {food_mesh}"
    )

    # Vitamin C must come through as Ascorbic Acid.
    if "component" in result.concept_resolutions:
        assert "Ascorbic Acid" in result.concept_resolutions["component"].mesh_terms

    # --- Retrieval-depth sanity ---
    assert len(result.papers) >= 15, (
        f"expected ≥15 papers, got {len(result.papers)}"
    )

    # At least one paper should be an RCT, systematic review, or meta-analysis —
    # these are the strongest evidence tiers our agent is told to prioritise.
    strong_types = {
        "randomized controlled trial",
        "systematic review",
        "meta-analysis",
    }
    has_strong = any(
        pt.lower() in strong_types
        for p in result.papers
        for pt in p.pub_types
    )
    assert has_strong, "no RCT / SR / meta-analysis in retrieved papers"
