"""Live-LLM integration smoke test (Task 7).

Skipped by default — set ``RUN_LIVE_TESTS=1`` to run.  Do NOT run in CI.
"""

import os

import pytest

from src.extraction.extractor import ClaimExtractor
from src.extraction.llm_client import LLMClient


@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"),
    reason="live LLM test (set RUN_LIVE_TESTS=1 to run)",
)
def test_live_extraction_turmeric_inflammation():
    client = LLMClient(model="gemini-2.5-pro")
    extractor = ClaimExtractor(client)
    pico = extractor.extract("Is turmeric good for inflammation?")

    assert pico.food.value == "turmeric"
    assert pico.is_food_claim is True
    assert "population" in pico.ambiguous_slots
