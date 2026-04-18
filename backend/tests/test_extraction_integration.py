"""Live-LLM integration smoke test (Task 7).

Skipped by default — set ``RUN_LIVE_TESTS=1`` to run.  Do NOT run in CI.

Defaults to ``gemini-2.5-flash`` because ``gemini-2.5-pro`` has no
free-tier quota on Google AI Studio (limit=0). Override the model with
``LIVE_LLM_MODEL=gemini-2.5-pro`` if you're on a paid tier.
"""

import os

import pytest

from backend.src.extraction.extractor import ClaimExtractor
from backend.src.extraction.llm_client import LLMClient


@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"),
    reason="live LLM test (set RUN_LIVE_TESTS=1 to run)",
)
def test_live_extraction_turmeric_inflammation():
    model = os.getenv("LIVE_LLM_MODEL", "gemini-2.5-flash")
    client = LLMClient(model=model)
    extractor = ClaimExtractor(client)
    pico = extractor.extract("Is turmeric good for inflammation?")

    assert pico.food.value == "turmeric"
    assert pico.is_food_claim is True
    assert "population" in pico.ambiguous_slots
