"""Data models for Station 3: Retrieval.

``RetrievedPaper`` is the unit of evidence that flows into Station 4.
``RetrievalResult`` is the complete output of the retrieval agent.
``ESearchResult`` is the shape returned by PubMed's esearch endpoint.

Note: ``LockedPICO`` is NOT defined here. It lives in ``src.schemas``
and is shared across all stations.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ESearchResult(BaseModel):
    """Result of a PubMed esearch call — PMIDs plus total hit count."""

    query: str
    pmids: list[str]
    total_count: int
    returned_count: int


class CAERSReport(BaseModel):
    """A single adverse-event report from FDA CAERS (openFDA food/event).

    Consumer/clinician-submitted, uncorroborated. Station 4 must not
    characterise these as proof of harm — treat as signals, not evidence.
    """

    report_id: str                  # openFDA report_number
    date: str                       # ISO YYYY-MM-DD (converted from openFDA YYYYMMDD)
    product_name: str               # first suspect product's brand name
    industry_name: str              # first suspect product's industry/category
    reactions: list[str]            # MedDRA preferred terms
    outcomes: list[str]             # e.g. "Hospitalization", "Death", "Other serious"


class Concept(BaseModel):
    """A user-facing PICO term resolved to validated MeSH vocabulary.

    Produced by the concept resolver and consumed by the query builder.
    The critical field is ``mesh_terms`` — the list of real MeSH Headings
    we've confirmed will actually return results on PubMed. If
    ``validated`` is False, every proposed MeSH term failed its hit-count
    check and the query builder should fall back to ``tiab_synonyms``.
    """

    user_term: str                  # original PICO value, e.g. "orange"
    mesh_terms: list[str]           # validated MeSH Headings, e.g. ["Citrus sinensis"]
    tiab_synonyms: list[str]        # free-text fallback terms, e.g. ["orange", "oranges"]
    validated: bool                 # True if ≥1 mesh_term passed the hit-count threshold
    notes: Optional[str] = None     # free-text explanation from the LLM / resolver


class RetrievedPaper(BaseModel):
    """A paper retrieved by the agent, ready for Station 4 (Synthesis)."""

    pmid: str
    title: str
    abstract: str = ""
    pub_types: list[str] = []
    journal: str = ""
    year: Optional[int] = None
    authors: list[str] = []
    is_retracted: bool = False
    source_query: str = ""          # which executed query first surfaced this PMID


class ExecutedQueryModel(BaseModel):
    """Pydantic twin of agent_state.ExecutedQuery, for serialisation."""

    query_string: str
    rationale: str
    hit_count: int
    papers_fetched: int
    pmids: list[str] = []


class RetrievalResult(BaseModel):
    """Output of the agentic retrieval loop — consumed by Station 4."""

    locked_pico: "PartialPICO"
    concept_resolutions: dict[str, Concept]
    queries_executed: list[ExecutedQueryModel]
    papers: list[RetrievedPaper]
    caers_reports: list[CAERSReport] = []
    retrieval_notes: list[str] = []
    total_iterations: int = 0
    budget_exhausted: bool = False
    finish_rationale: Optional[str] = None


# Avoid a circular import: ``PartialPICO`` is referenced as a forward ref above.
from src.schemas import PartialPICO  # noqa: E402
RetrievalResult.model_rebuild()
