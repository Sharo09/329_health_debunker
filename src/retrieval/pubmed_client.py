"""PubMed E-utilities API client for Station 3.

Wraps two NCBI endpoints:
    esearch.fcgi  — text search → list of PMIDs + total hit count
    efetch.fcgi   — fetch full XML records for a list of PMIDs

Features
--------
- API key injection (free key raises rate limit from 3 → 10 req/sec).
- Automatic throttling to stay within NCBI's rate limits.
- Exponential-backoff retry on transient network failures.
- Robust XML parsing that handles:
    - Structured abstracts (multiple <AbstractText Label=...> sections)
    - Missing abstracts, titles, years, authors
    - Retraction notices in publication types
    - Mixed XML content (bold tags, italics etc. inside abstract text)
    - Non-UTF-8 characters

Get a free NCBI API key at: https://www.ncbi.nlm.nih.gov/account/
Set it as the environment variable NCBI_API_KEY.
"""

from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.retrieval.errors import PubMedAPIError
from src.retrieval.schemas import Paper

logger = logging.getLogger(__name__)

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_DELAY_WITH_KEY = 0.11      # seconds  (just under 10 req/sec)
_DELAY_WITHOUT_KEY = 0.35   # seconds  (just under 3 req/sec)


class PubMedRateLimitError(PubMedAPIError):
    """Raised on HTTP 429 so tenacity can retry with long backoff."""


def _is_retryable(exc: BaseException) -> bool:
    """Retry transient network errors and rate-limit (429) responses."""
    return isinstance(
        exc, (requests.Timeout, requests.ConnectionError, PubMedRateLimitError)
    )


class PubMedClient:
    """Thin, robust wrapper around NCBI E-utilities."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("NCBI_API_KEY")
        self._delay = _DELAY_WITH_KEY if self.api_key else _DELAY_WITHOUT_KEY
        self._last_request: float = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": "HealthMythDebunker/1.0 (academic research)"}
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str, max_results: int = 80) -> tuple[list[str], int]:
        """
        Run an esearch query against PubMed.

        Parameters
        ----------
        query       : PubMed query string
        max_results : maximum number of PMIDs to return

        Returns
        -------
        (pmids, total_count)
            pmids        — list of PMID strings (up to max_results)
            total_count  — total number of records PubMed says match
                           (may be > len(pmids) when we cap the fetch)
        """
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "usehistory": "n",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        data = self._get_json("esearch.fcgi", params)
        result = data.get("esearchresult", {})

        # Log any phrases PubMed couldn't parse — useful for debugging
        # malformed queries produced by the QueryBuilder.
        error_list = result.get("errorlist", {})
        bad_phrases = error_list.get("phrasesnotfound", [])
        if bad_phrases:
            logger.warning("PubMed could not parse these phrases: %s", bad_phrases)

        pmids: list[str] = result.get("idlist", [])
        total: int = int(result.get("count", 0))
        logger.info("esearch: %d total hits; returning %d PMIDs.", total, len(pmids))
        return pmids, total

    def fetch(self, pmids: list[str]) -> list[Paper]:
        """
        Fetch full PubMed records (abstract, metadata) for a list of PMIDs.

        Parameters
        ----------
        pmids : list of PMID strings

        Returns
        -------
        List of Paper objects. Papers that fail to parse are skipped with a
        warning rather than crashing the whole batch.
        """
        if not pmids:
            return []

        # PubMed recommends batching large requests.
        # For our capped fetch size (≤80) a single request is fine.
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "rettype": "abstract",
            "retmode": "xml",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        xml_text = self._get_xml("efetch.fcgi", params)
        papers = self._parse_xml(xml_text)
        logger.info("efetch: parsed %d/%d papers.", len(papers), len(pmids))
        return papers

    # ------------------------------------------------------------------
    # Internal: HTTP helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_request = time.time()

    def _raise_for_status(self, resp: requests.Response, endpoint: str) -> None:
        """Raise a typed error for HTTP failures — 429 gets its own class
        so tenacity can retry it with long backoff."""
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                msg = f"PubMed 429 rate-limited on {endpoint}"
                if retry_after:
                    msg += f" (Retry-After={retry_after}s)"
                    try:
                        time.sleep(min(float(retry_after), 60))
                    except ValueError:
                        pass
                raise PubMedRateLimitError(msg) from e
            raise PubMedAPIError(f"PubMed HTTP error on {endpoint}: {e}") from e

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(6),
    )
    def _get_json(self, endpoint: str, params: dict) -> dict:
        self._throttle()
        resp = self._session.get(f"{PUBMED_BASE}/{endpoint}", params=params, timeout=20)
        self._raise_for_status(resp, endpoint)
        return resp.json()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(6),
    )
    def _get_xml(self, endpoint: str, params: dict) -> str:
        self._throttle()
        resp = self._session.get(f"{PUBMED_BASE}/{endpoint}", params=params, timeout=30)
        self._raise_for_status(resp, endpoint)
        return resp.text

    # ------------------------------------------------------------------
    # Internal: XML parsing
    # ------------------------------------------------------------------

    def _parse_xml(self, xml_text: str) -> list[Paper]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error("PubMed XML parse failed: %s", e)
            return []

        papers: list[Paper] = []
        for article_el in root.findall(".//PubmedArticle"):
            try:
                paper = self._parse_article(article_el)
                if paper is not None:
                    papers.append(paper)
            except Exception as exc:   # never drop the whole batch for one bad record
                pmid_el = article_el.find(".//PMID")
                pmid_hint = pmid_el.text if pmid_el is not None else "unknown"
                logger.warning("Skipping malformed article PMID=%s: %s", pmid_hint, exc)
        return papers

    def _parse_article(self, el: ET.Element) -> Optional[Paper]:
        # PMID — required; skip if absent
        pmid_el = el.find(".//PMID")
        if pmid_el is None or not pmid_el.text:
            return None
        pmid = pmid_el.text.strip()

        # Title — use itertext() to handle inline markup (<i>, <b>, etc.)
        title = _itertext(el.find(".//ArticleTitle")) or "[No title]"

        # Abstract — may be structured (multiple labelled sections)
        abstract_parts: list[str] = []
        for ab in el.findall(".//AbstractText"):
            label = ab.get("Label")
            text = _itertext(ab)
            if not text:
                continue
            abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abstract_parts)

        # Authors
        authors: list[str] = []
        for author_el in el.findall(".//Author"):
            last = _itertext(author_el.find("LastName"))
            initials = _itertext(author_el.find("Initials"))
            if last:
                authors.append(f"{last} {initials}".strip())

        # Journal
        journal = _itertext(el.find(".//Journal/Title")) or "Unknown Journal"

        # Publication year — check two common locations
        pub_year: Optional[int] = None
        for year_path in (".//JournalIssue/PubDate/Year", ".//PubDate/Year"):
            year_el = el.find(year_path)
            if year_el is not None and year_el.text:
                try:
                    pub_year = int(year_el.text)
                    break
                except ValueError:
                    pass

        # Publication types
        pub_types = [
            pt.text.strip()
            for pt in el.findall(".//PublicationTypeList/PublicationType")
            if pt.text
        ]

        # MeSH terms (descriptor names only, not qualifiers)
        mesh_terms = [
            _itertext(mh.find("DescriptorName"))
            for mh in el.findall(".//MeshHeadingList/MeshHeading")
        ]
        mesh_terms = [m for m in mesh_terms if m]

        # DOI
        doi: Optional[str] = None
        for aid in el.findall(".//ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi" and aid.text:
                doi = aid.text.strip()

        # Retraction flag — covers both "Retraction of Publication"
        # and "Retracted Publication" publication types
        is_retracted = any("retract" in (pt or "").lower() for pt in pub_types)
        if is_retracted:
            logger.warning("PMID %s is retracted.", pmid)

        # Language (default "eng" if absent)
        language = _itertext(el.find(".//Language")) or "eng"

        return Paper(
            pmid=pmid,
            title=title,
            abstract=abstract,
            authors=authors,
            journal=journal,
            pub_year=pub_year,
            pub_types=pub_types,
            mesh_terms=mesh_terms,
            doi=doi,
            is_retracted=is_retracted,
            language=language,
        )


def _itertext(el: Optional[ET.Element]) -> str:
    """Join all text content inside an element, handling inline markup."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()