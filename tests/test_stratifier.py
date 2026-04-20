"""Tests for Station 4's paper value extractor (Patch B Task 3)."""

from __future__ import annotations

import json
import threading
import time
from typing import Callable

import pytest

from src.extraction.llm_client import LLMClient
from src.synthesis.schemas import Paper
from src.synthesis.stratifier import (
    STRATIFIER_EXTRACTION_PROMPT,
    ExtractedPaperValues,
    extract_paper_values,
    extract_values_in_parallel,
)


# ---------- scripted LLM helpers ----------


def _scripted_provider(
    route: Callable[[str], dict],
    barrier: threading.Event | None = None,
    tracker: "_Tracker | None" = None,
):
    """Return a provider callable whose output depends on the last user message.

    ``route`` takes the abstract text and returns the dict the scripted
    provider should emit as JSON. ``barrier`` (if set) is waited on by
    every call — lets tests force overlap to probe concurrency. ``tracker``
    (if set) is entered/exited around the provider body so peak concurrency
    can be measured.
    """

    def provider(messages, response_schema, model, temperature, **kwargs):
        user = next(m["content"] for m in messages if m["role"] == "user")
        # Strip the leading "Abstract: " and trailing "\nOutput:".
        abstract = user.split("Abstract: ", 1)[-1].split("\nOutput:", 1)[0]
        out = route(abstract)

        if tracker is not None:
            with tracker:
                if barrier is not None:
                    barrier.wait(timeout=5)
                return json.dumps(out)
        if barrier is not None:
            barrier.wait(timeout=5)
        return json.dumps(out)

    return provider


class _Tracker:
    """Reports peak concurrent entries across threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current = 0
        self.peak = 0

    def __enter__(self):
        with self._lock:
            self._current += 1
            if self._current > self.peak:
                self.peak = self._current
        return self

    def __exit__(self, *exc):
        with self._lock:
            self._current -= 1


def _client(provider, tmp_path) -> LLMClient:
    return LLMClient(
        model="test-model",
        log_file=str(tmp_path / "stratifier_llm.jsonl"),
        provider=provider,
    )


def _paper(paper_id: str, abstract: str, title: str = "Title") -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title,
        extracted_claim="",
        abstract=abstract,
    )


# ---------- Schema checks ----------


def test_schema_defaults():
    v = ExtractedPaperValues(paper_id="X")
    assert v.dose_studied is None
    assert v.form_studied is None
    assert v.frequency_studied is None
    assert v.population_studied is None
    assert v.extraction_reasoning == ""


# ---------- Example round-trips from the spec prompt ----------


CURCUMIN_RCT_ABSTRACT = (
    "We conducted a randomized trial of curcumin supplementation at 500 mg "
    "twice daily for 12 weeks in 80 adults with knee osteoarthritis..."
)
CURCUMIN_RCT_OUTPUT = {
    "paper_id": "1",
    "dose_studied": "1000 mg/day (500 mg twice daily)",
    "form_studied": "supplement",
    "frequency_studied": "daily",
    "population_studied": "adults with knee osteoarthritis",
    "extraction_reasoning": "Explicit dose and form stated; population specified.",
}

META_ANALYSIS_ABSTRACT = (
    "This meta-analysis of 11 observational cohort studies examined "
    "dietary turmeric intake from spice consumption and inflammatory markers..."
)
META_ANALYSIS_OUTPUT = {
    "paper_id": "2",
    "dose_studied": None,
    "form_studied": "dietary",
    "frequency_studied": None,
    "population_studied": "general adult populations (meta-analysis)",
    "extraction_reasoning": "Form is dietary; dose and frequency not reported in abstract.",
}

IN_VITRO_ABSTRACT = (
    "In vitro study of curcumin at 10 uM on HeLa cell proliferation..."
)
IN_VITRO_OUTPUT = {
    "paper_id": "3",
    "dose_studied": "10 uM (in vitro concentration)",
    "form_studied": "isolated compound",
    "frequency_studied": None,
    "population_studied": "HeLa cell line (in vitro)",
    "extraction_reasoning": "In vitro; population is cell line, not human.",
}


def test_extract_rct(tmp_path):
    llm = _client(
        _scripted_provider(lambda _abstract: CURCUMIN_RCT_OUTPUT),
        tmp_path,
    )
    p = _paper("1", CURCUMIN_RCT_ABSTRACT)
    out = extract_paper_values(p, llm)
    assert out.paper_id == "1"
    assert out.dose_studied == "1000 mg/day (500 mg twice daily)"
    assert out.form_studied == "supplement"
    assert out.frequency_studied == "daily"
    assert "knee osteoarthritis" in (out.population_studied or "")


def test_extract_meta_analysis_has_null_dose(tmp_path):
    llm = _client(
        _scripted_provider(lambda _abstract: META_ANALYSIS_OUTPUT),
        tmp_path,
    )
    out = extract_paper_values(_paper("2", META_ANALYSIS_ABSTRACT), llm)
    # Null fields must be None — not "", "N/A", or "unknown".
    assert out.dose_studied is None
    assert out.frequency_studied is None
    assert out.form_studied == "dietary"


def test_extract_in_vitro(tmp_path):
    llm = _client(
        _scripted_provider(lambda _abstract: IN_VITRO_OUTPUT),
        tmp_path,
    )
    out = extract_paper_values(_paper("3", IN_VITRO_ABSTRACT), llm)
    assert out.form_studied == "isolated compound"
    assert "HeLa" in (out.population_studied or "") or "in vitro" in (out.population_studied or "")


# ---------- Null handling ----------


def test_completely_null_extraction(tmp_path):
    llm = _client(
        _scripted_provider(lambda _a: {
            "paper_id": "blank",
            "dose_studied": None,
            "form_studied": None,
            "frequency_studied": None,
            "population_studied": None,
            "extraction_reasoning": "Abstract is a press blurb without methods.",
        }),
        tmp_path,
    )
    out = extract_paper_values(_paper("blank", "A brief note about some study."), llm)
    assert out.dose_studied is None
    assert out.form_studied is None
    assert out.frequency_studied is None
    assert out.population_studied is None


def test_llm_exception_fails_open(tmp_path):
    def provider(messages, response_schema, model, temperature, **kwargs):
        raise RuntimeError("gemini down")

    llm = _client(provider, tmp_path)
    out = extract_paper_values(_paper("X", "some abstract"), llm)
    assert out.paper_id == "X"
    assert out.dose_studied is None
    assert "failed" in out.extraction_reasoning.lower()


def test_empty_abstract_returns_null(tmp_path):
    # No abstract AND no extracted_claim AND no title → skip LLM entirely.
    llm = _client(
        _scripted_provider(
            lambda _a: pytest.fail("LLM should not be called for empty paper")
        ),
        tmp_path,
    )
    p = Paper(paper_id="empty", title="", extracted_claim="", abstract="")
    out = extract_paper_values(p, llm)
    assert out.paper_id == "empty"
    assert out.dose_studied is None
    assert "no abstract" in out.extraction_reasoning.lower()


def test_fallback_to_title_and_extracted_claim(tmp_path):
    calls: list[str] = []

    def route(abstract: str) -> dict:
        calls.append(abstract)
        return {
            "paper_id": "F",
            "dose_studied": None,
            "form_studied": "dietary",
            "frequency_studied": None,
            "population_studied": "adults",
            "extraction_reasoning": "From title/claim.",
        }

    llm = _client(_scripted_provider(route), tmp_path)
    p = Paper(
        paper_id="F",
        title="Dietary fibre and CVD in adults",
        extracted_claim="Higher fibre intake was associated with lower risk.",
        abstract="",  # empty → fallback kicks in
    )
    out = extract_paper_values(p, llm)
    assert out.form_studied == "dietary"
    # Prompt text that actually went out carries title + claim:
    assert "Dietary fibre" in calls[0]
    assert "Higher fibre" in calls[0]


# ---------- LLM always pinned to the paper_id we passed ----------


def test_paper_id_enforced_on_output(tmp_path):
    # LLM returns a different paper_id; wrapper must overwrite with ours.
    llm = _client(
        _scripted_provider(lambda _a: {
            "paper_id": "wrong-id-from-llm",
            "dose_studied": "100 mg",
            "form_studied": "supplement",
            "frequency_studied": None,
            "population_studied": None,
            "extraction_reasoning": "Example",
        }),
        tmp_path,
    )
    out = extract_paper_values(_paper("PMID-42", "Some abstract text."), llm)
    assert out.paper_id == "PMID-42"


# ---------- Parallel extractor ----------


def test_parallel_returns_dict_keyed_by_paper_id(tmp_path):
    llm = _client(
        _scripted_provider(lambda _a: {
            "paper_id": "ignored",
            "dose_studied": "100 mg",
            "form_studied": "supplement",
            "frequency_studied": None,
            "population_studied": None,
            "extraction_reasoning": "x",
        }),
        tmp_path,
    )
    papers = [_paper(str(i), f"Abstract {i}") for i in range(6)]
    out = extract_values_in_parallel(papers, llm, max_workers=4)
    assert set(out.keys()) == {str(i) for i in range(6)}
    for pid, val in out.items():
        assert val.paper_id == pid
        assert val.form_studied == "supplement"


def test_parallel_empty_input():
    # No provider needed — function returns {} before hitting the pool.
    out = extract_values_in_parallel([], llm=None)  # type: ignore[arg-type]
    assert out == {}


def test_parallel_respects_max_workers_cap(tmp_path):
    """Verify the pool never runs more than ``max_workers`` concurrent calls.

    Each worker enters the tracker and waits on a barrier; we release
    the barrier after sleeping briefly — if more than 4 workers have
    entered, tracker.peak will exceed 4.
    """
    tracker = _Tracker()
    start_barrier = threading.Event()

    def slow_route(_abstract: str) -> dict:
        # Small sleep in the critical section to force overlap across
        # threads without stalling the test for long.
        time.sleep(0.05)
        return {
            "paper_id": "ignored",
            "dose_studied": None,
            "form_studied": None,
            "frequency_studied": None,
            "population_studied": None,
            "extraction_reasoning": "x",
        }

    llm = _client(
        _scripted_provider(slow_route, barrier=start_barrier, tracker=tracker),
        tmp_path,
    )
    papers = [_paper(str(i), f"Abstract {i}") for i in range(12)]

    def release_after_short_delay():
        time.sleep(0.1)
        start_barrier.set()

    releaser = threading.Thread(target=release_after_short_delay)
    releaser.start()
    try:
        out = extract_values_in_parallel(papers, llm, max_workers=4)
    finally:
        start_barrier.set()
        releaser.join()

    assert len(out) == 12
    assert tracker.peak <= 4, (
        f"peak concurrency {tracker.peak} exceeded max_workers=4"
    )


def test_parallel_max_workers_clamped_to_paper_count(tmp_path):
    """Passing max_workers=10 with 2 papers shouldn't spawn 10 threads."""
    tracker = _Tracker()

    def route(_abstract: str) -> dict:
        time.sleep(0.02)
        return {
            "paper_id": "ignored",
            "dose_studied": None,
            "form_studied": None,
            "frequency_studied": None,
            "population_studied": None,
            "extraction_reasoning": "x",
        }

    llm = _client(_scripted_provider(route, tracker=tracker), tmp_path)
    out = extract_values_in_parallel(
        [_paper("a", "x"), _paper("b", "y")],
        llm,
        max_workers=10,
    )
    assert len(out) == 2
    assert tracker.peak <= 2


# ---------- Sanity on the prompt itself ----------


def test_prompt_mentions_four_fields():
    for fragment in ("dose", "form", "frequency", "population"):
        assert fragment in STRATIFIER_EXTRACTION_PROMPT.lower()
