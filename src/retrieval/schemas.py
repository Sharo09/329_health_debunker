"""Data models for Station 3: Retrieval.

``Paper`` is the unit of evidence that flows into Station 4.
``RetrievalResult`` is the complete output of the retrieval agent.
``ESearchResult`` is the shape returned by PubMed's esearch endpoint.

Note: ``LockedPICO`` is NOT defined here. It lives in ``src.schemas``
and is shared across all stations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# Spec-aligned Paper / RetrievalResult (used by the new retrieval agent).
# Kept alongside the legacy ``Paper`` dataclass so Sharon's agent keeps
# working during the rebuild.
# ---------------------------------------------------------------------------

class RetrievedPaper(BaseModel):
    """A paper retrieved by the new agent — pydantic, with ``source_query``."""

    pmid: str
    title: str
    abstract: str = ""
    pub_types: list[str] = []
    journal: str = ""
    year: Optional[int] = None
    authors: list[str] = []
    is_retracted: bool = False
    source_query: str = ""          # which executed query first surfaced this PMID


class RetrievalResultV2(BaseModel):
    """Output of the new agentic retrieval loop (Task 6)."""

    locked_pico: "PartialPICO"
    concept_resolutions: dict[str, Concept]
    queries_executed: list["ExecutedQueryModel"]
    papers: list[RetrievedPaper]
    caers_reports: list[CAERSReport] = []
    retrieval_notes: list[str] = []
    total_iterations: int = 0
    budget_exhausted: bool = False
    finish_rationale: Optional[str] = None


class ExecutedQueryModel(BaseModel):
    """Pydantic twin of agent_state.ExecutedQuery, for serialisation."""

    query_string: str
    rationale: str
    hit_count: int
    papers_fetched: int
    pmids: list[str] = []


# Avoid a circular import: ``PartialPICO`` is referenced as a forward ref.
from src.schemas import PartialPICO  # noqa: E402
RetrievalResultV2.model_rebuild()


@dataclass
class Paper:
    """
    A single paper retrieved from PubMed, ready for Station 4 (Synthesis).

    Fields
    ------
    pmid            Unique PubMed identifier (string, e.g. "36543210").
    title           Article title.
    abstract        Full abstract text. May be empty if the record has none.
    authors         List of author names in "LastName Initials" format.
    journal         Journal title as indexed in PubMed.
    pub_year        Four-digit publication year, or None if not parseable.
    pub_types       List of PubMed publication type strings,
                    e.g. ["Randomized Controlled Trial", "Clinical Trial"].
    mesh_terms      MeSH descriptor names attached to this record.
    doi             Digital Object Identifier, or None.
    is_retracted    True if a retraction notice is indexed against this PMID.
                    Station 4 should handle retracted papers separately.
    language        Two- or three-letter ISO language code (e.g. "eng").
    relevance_score Filled in by Station 4's relevance scorer (0.0–1.0).
                    Left at 0.0 by Station 3.
    relevance_reasoning
                    One-sentence LLM explanation of the score.
                    Left empty by Station 3.
    """

    pmid: str
    title: str
    abstract: str
    authors: list[str]
    journal: str
    pub_year: Optional[int]
    pub_types: list[str]
    mesh_terms: list[str]
    doi: Optional[str] = None
    is_retracted: bool = False
    language: str = "eng"

    # --- Filled in by Station 4, not Station 3 ---
    relevance_score: float = 0.0
    relevance_reasoning: str = ""


@dataclass
class RetrievalResult:
    """
    The complete output of Station 3, consumed by Station 4 (Synthesis).

    Fields
    ------
    papers              List of retrieved Paper objects, ordered by PubMed
                        relevance ranking (Station 4 will re-sort by its own
                        relevance score).
    query_used          The final PubMed query string that produced results.
    relaxation_level    Integer indicating how many times the query was
                        loosened before results passed the threshold.
                        0 = fully specified; higher = more relaxed.
    total_pubmed_hits   Raw hit count from PubMed (may exceed len(papers)
                        when we cap the fetch).
    below_threshold     True if fewer than MIN_PAPER_THRESHOLD papers were
                        returned after all relaxation levels were tried.
                        Station 4 should warn the user in this case.
    audit_log           List of dicts recording every query attempted, its
                        hit count, and the reason for any relaxation step.
                        This is Station 3's contribution to the audit trail.
    """

    papers: list[Paper]
    query_used: str
    relaxation_level: int
    total_pubmed_hits: int
    below_threshold: bool
    audit_log: list[dict] = field(default_factory=list)