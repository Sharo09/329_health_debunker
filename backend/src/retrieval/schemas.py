"""Data models for Station 3: Retrieval.

``Paper`` is the unit of evidence that flows into Station 4.
``RetrievalResult`` is the complete output of the retrieval agent.

Note: ``LockedPICO`` is NOT defined here. It lives in ``src.schemas``
and is shared across all stations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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