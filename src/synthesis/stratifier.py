"""Paper value extractor — Task 3 of elicitation Patch B.

For each retrieved paper, uses an LLM to pull four features from the
abstract:

- ``dose_studied`` — e.g. ``"500 mg/day"``, ``"2-3 cups/day"``
- ``form_studied`` — e.g. ``"dietary"``, ``"supplement"``, ``"extract"``
- ``frequency_studied`` — e.g. ``"daily"``, ``"weekly"``
- ``population_studied`` — e.g. ``"healthy adults"``, ``"T2D patients"``

These are *what the paper actually reports*. The stratum assigner
(Task 4) then compares them to the user's stated values to bucket
papers per slot.

Design notes:

- Abstract-only. If the abstract doesn't report a feature, return
  ``None``. Do NOT infer from context or common practice — spurious
  values here corrupt every downstream stratum.
- Thinking budget is disabled — this is a factual extraction task
  from a bounded text; the reasoning pass on Gemini 2.5 Flash adds
  latency without accuracy gains.
- Parallel fan-out at ``max_workers=4`` respects the free-tier
  rate limits (5 req/min on Flash). 40 papers ≈ 10 batches of 4.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from src.extraction.llm_client import LLMClient
from src.synthesis.schemas import Paper

logger = logging.getLogger(__name__)

DEFAULT_MAX_WORKERS = 4


STRATIFIER_EXTRACTION_PROMPT = """\
You extract four specific features from a research paper abstract:
what dose/amount, form, frequency, and population were studied. Return
values that the paper ACTUALLY reports. If the paper doesn't report a
feature, return null. Do NOT infer values from context or common
practice.

Return a JSON object matching the schema. Be brief and factual.

EXAMPLES

Abstract: "We conducted a randomized trial of curcumin supplementation
at 500 mg twice daily for 12 weeks in 80 adults with knee
osteoarthritis..."
Output: {
  "dose_studied": "1000 mg/day (500 mg twice daily)",
  "form_studied": "supplement",
  "frequency_studied": "daily",
  "population_studied": "adults with knee osteoarthritis",
  "extraction_reasoning": "Explicit dose and form stated; population specified."
}

Abstract: "This meta-analysis of 11 observational cohort studies examined
dietary turmeric intake from spice consumption and inflammatory markers..."
Output: {
  "dose_studied": null,
  "form_studied": "dietary",
  "frequency_studied": null,
  "population_studied": "general adult populations (meta-analysis)",
  "extraction_reasoning": "Form is dietary; dose and frequency not reported in abstract."
}

Abstract: "In vitro study of curcumin at 10 uM on HeLa cell proliferation..."
Output: {
  "dose_studied": "10 uM (in vitro concentration)",
  "form_studied": "isolated compound",
  "frequency_studied": null,
  "population_studied": "HeLa cell line (in vitro)",
  "extraction_reasoning": "In vitro; population is cell line, not human."
}
"""


class ExtractedPaperValues(BaseModel):
    """What the paper itself studied — extracted from abstract."""

    paper_id: str
    dose_studied: Optional[str] = Field(
        default=None,
        description="Paper's studied dose; None if unreported.",
    )
    form_studied: Optional[str] = Field(
        default=None,
        description=(
            "Paper's studied form — e.g. 'dietary', 'supplement', "
            "'extract', 'isolated compound'. None if unreported."
        ),
    )
    frequency_studied: Optional[str] = Field(default=None)
    population_studied: Optional[str] = Field(default=None)
    extraction_reasoning: str = Field(default="")


def _abstract_for(paper: Paper) -> str:
    """Pick the richest text we have for a paper.

    Prefers ``abstract`` when populated; otherwise falls back to the
    title plus ``extracted_claim`` so at least population/form hints
    often encoded in the title still get a chance.
    """
    if paper.abstract and paper.abstract.strip():
        return paper.abstract.strip()
    parts = [paper.title.strip() if paper.title else ""]
    if paper.extracted_claim and paper.extracted_claim.strip():
        parts.append(paper.extracted_claim.strip())
    return ". ".join(p for p in parts if p)


def extract_paper_values(
    paper: Paper,
    llm: LLMClient,
) -> ExtractedPaperValues:
    """Extract dose/form/frequency/population from one paper's abstract.

    Returns an ``ExtractedPaperValues`` with ``paper_id`` always set.
    Any feature the LLM cannot ground in the abstract is ``None``.
    On LLM failure, returns an all-null ``ExtractedPaperValues`` with
    an explanatory reasoning string — fail open so one bad paper
    doesn't abort the whole stratification.
    """
    text = _abstract_for(paper)
    if not text:
        return ExtractedPaperValues(
            paper_id=paper.paper_id,
            extraction_reasoning="No abstract text available; all features null.",
        )

    messages = [
        {"role": "system", "content": STRATIFIER_EXTRACTION_PROMPT},
        {
            "role": "user",
            "content": f"Abstract: {text}\nOutput:",
        },
    ]

    try:
        parsed = llm.extract(messages, ExtractedPaperValues)
    except Exception as exc:  # noqa: BLE001 — intentional fail-open
        logger.warning(
            "stratifier: LLM extract failed for paper %s — %s",
            paper.paper_id, exc,
        )
        return ExtractedPaperValues(
            paper_id=paper.paper_id,
            extraction_reasoning=f"LLM extract failed: {exc}",
        )

    # Enforce paper_id on the returned object — the LLM may echo something
    # else (or nothing) for that field, and the stratum assigner keys on it.
    parsed.paper_id = paper.paper_id
    return parsed


def extract_values_in_parallel(
    papers: Iterable[Paper],
    llm: LLMClient,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, ExtractedPaperValues]:
    """Fan out extraction across papers with a bounded thread pool.

    Returns a dict keyed by ``paper_id`` so callers can align results
    with the per-paper scores in the stratum assigner. Order of calls
    is not deterministic (thread-pool execution). Per-paper failures
    are swallowed by ``extract_paper_values``; this wrapper also
    swallows unexpected executor errors so the synthesis stage can
    proceed with whatever we got.
    """
    papers = list(papers)
    if not papers:
        return {}
    workers = max(1, min(max_workers, len(papers)))

    results: dict[str, ExtractedPaperValues] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(extract_paper_values, p, llm): p.paper_id
            for p in papers
        }
        for fut in futures:
            paper_id = futures[fut]
            try:
                results[paper_id] = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "stratifier: worker failed for paper %s — %s",
                    paper_id, exc,
                )
                results[paper_id] = ExtractedPaperValues(
                    paper_id=paper_id,
                    extraction_reasoning=f"worker failed: {exc}",
                )
    return results


class _ConcurrencyTracker:
    """Records the peak concurrency observed across a critical section.

    Exposed for test use so the thread-pool cap can be verified
    empirically — if ``max_workers=4`` is honoured, ``peak`` should
    never exceed 4 regardless of paper count.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current = 0
        self.peak = 0

    def __enter__(self) -> "_ConcurrencyTracker":
        with self._lock:
            self._current += 1
            if self._current > self.peak:
                self.peak = self._current
        return self

    def __exit__(self, *exc) -> None:
        with self._lock:
            self._current -= 1
