"""PubMed E-utilities API client for Station 3.

Thin wrapper over three NCBI endpoints:

    esearch.fcgi  — text search → PMIDs + total hit count (and a count-only variant)
    efetch.fcgi   — fetch full XML records for a list of PMIDs
    (esummary is not yet exposed; add when an agent tool actually needs it)

Features
--------
- Token-bucket style rate limiting (3 req/sec anonymous; 10 req/sec with API key).
- ``tenacity``-based retries on 429 and 5xx. NO retry on 4xx client errors.
- Pluggable cache (any Mapping-like object; ``None`` disables caching).
- XML parsing that handles labeled abstract sections
  (BACKGROUND, METHODS, RESULTS, CONCLUSIONS) and mixed inline content.
- Typed exceptions: ``PubMedNetworkError`` for transport/HTTP, ``PubMedParseError``
  for malformed response bodies.

Environment
-----------
- ``PUBMED_API_KEY`` (preferred) or ``NCBI_API_KEY`` raises the rate limit
  from 3 to 10 req/sec. Free from ncbi.nlm.nih.gov/account.

The client exposes both the new API (``esearch``/``count``/``fetch_details``/
``check_retractions``) required by the retrieval spec and the legacy
``search``/``fetch`` shims used by Sharon's original agent — so work in
progress isn't blocked while the rest of the stack is rebuilt.
"""

from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from threading import Lock
from typing import Any, Mapping, MutableMapping, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.retrieval.errors import (
    PubMedNetworkError,
    PubMedParseError,
    PubMedRateLimitError,
)
from src.retrieval.schemas import ESearchResult

logger = logging.getLogger(__name__)

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_DELAY_WITH_KEY = 0.11      # seconds, just under 10 req/sec
_DELAY_WITHOUT_KEY = 0.35   # seconds, just under 3 req/sec


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Minimum-interval rate limiter. Thread-safe via a single lock."""

    def __init__(self, min_interval: float):
        self._interval = min_interval
        self._last = 0.0
        self._lock = Lock()

    def wait(self, now_fn=time.monotonic, sleep_fn=time.sleep) -> None:
        with self._lock:
            now = now_fn()
            elapsed = now - self._last
            if elapsed < self._interval:
                sleep_fn(self._interval - elapsed)
                now = now_fn()
            self._last = now


# ---------------------------------------------------------------------------
# Retry predicate
# ---------------------------------------------------------------------------

def _is_retryable(exc: BaseException) -> bool:
    """Retry transport errors, 429s, and 5xx responses. Fail fast on 4xx."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, PubMedNetworkError):
        if exc.status_code is None:
            return True
        if exc.status_code == 429:
            return True
        if 500 <= exc.status_code < 600:
            return True
        return False
    return False


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class PubMedClient:
    """Thin, robust wrapper around NCBI E-utilities."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[MutableMapping[str, Any]] = None,
        session: Optional[requests.Session] = None,
    ):
        self.api_key = (
            api_key
            or os.getenv("PUBMED_API_KEY")
            or os.getenv("NCBI_API_KEY")
        )
        self._limiter = _RateLimiter(
            _DELAY_WITH_KEY if self.api_key else _DELAY_WITHOUT_KEY
        )
        self._cache = cache  # None disables caching
        self._session = session or requests.Session()
        self._session.headers.setdefault(
            "User-Agent", "HealthMythDebunker/1.0 (academic research)"
        )

    # ------------------------------------------------------------------
    # Public API — new (spec-aligned)
    # ------------------------------------------------------------------

    def esearch(
        self,
        query: str,
        max_results: int = 100,
        sort: str = "relevance",
    ) -> ESearchResult:
        """Search PubMed; return PMIDs and total hit count."""
        key = f"esearch::{sort}::{max_results}::{query}"
        result = self._cached(key, lambda: self._do_esearch(query, max_results, sort))
        # Cache stores dict (for JSON-safe serialisation by future cache.py).
        if isinstance(result, dict):
            return ESearchResult(**result)
        return result

    def count(self, query: str) -> int:
        """Return only the hit count for a query. Cheaper than esearch."""
        key = f"count::{query}"
        return self._cached(key, lambda: self._do_count(query))

    def fetch_details(self, pmids: list[str]) -> list[dict]:
        """Fetch full records (title, abstract, authors, metadata) for PMIDs.

        Batches requests into groups of 200 (efetch's sweet spot). Returns a
        list of dicts — the agent layer wraps them in ``Paper`` objects with
        ``source_query`` attached.
        """
        if not pmids:
            return []
        all_records: list[dict] = []
        for batch_start in range(0, len(pmids), 200):
            batch = pmids[batch_start : batch_start + 200]
            # Sort for a stable cache key regardless of input order.
            cache_key = "fetch::" + ",".join(sorted(batch))
            records = self._cached(cache_key, lambda b=batch: self._do_fetch(b))
            all_records.extend(records)
        return all_records

    def check_retractions(self, pmids: list[str]) -> set[str]:
        """Return the subset of ``pmids`` that are retracted."""
        if not pmids:
            return set()
        retracted: set[str] = set()
        for record in self.fetch_details(pmids):
            if "Retracted Publication" in record.get("pub_types", []):
                retracted.add(record["pmid"])
        return retracted

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cached(self, key: str, compute):
        if self._cache is None:
            return compute()
        if key in self._cache:
            return self._cache[key]
        value = compute()
        try:
            self._cache[key] = value
        except Exception as exc:
            logger.debug("Cache write failed for key %r: %s", key, exc)
        return value

    # ------------------------------------------------------------------
    # Low-level HTTP with retries
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _get(self, endpoint: str, params: dict) -> requests.Response:
        self._limiter.wait()
        full_params = dict(params)
        if self.api_key:
            full_params["api_key"] = self.api_key
        url = f"{PUBMED_BASE}/{endpoint}"
        try:
            resp = self._session.get(url, params=full_params, timeout=30)
        except requests.ConnectionError as exc:
            raise PubMedNetworkError(
                f"Connection error on {endpoint}: {exc}"
            ) from exc
        except requests.Timeout as exc:
            raise PubMedNetworkError(
                f"Timeout on {endpoint}: {exc}"
            ) from exc

        if resp.status_code != 200:
            retry_after = resp.headers.get("Retry-After") if resp.headers else None
            msg = f"PubMed {endpoint} returned {resp.status_code}"
            if resp.status_code == 429:
                if retry_after:
                    try:
                        time.sleep(min(float(retry_after), 60))
                    except ValueError:
                        pass
                raise PubMedRateLimitError(msg)
            raise PubMedNetworkError(msg, status_code=resp.status_code)
        return resp

    # ------------------------------------------------------------------
    # Endpoint implementations
    # ------------------------------------------------------------------

    def _do_esearch(
        self, query: str, max_results: int, sort: str
    ) -> ESearchResult:
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": sort,
            "usehistory": "n",
        }
        resp = self._get("esearch.fcgi", params)
        try:
            data = resp.json()
        except ValueError as exc:
            raise PubMedParseError(f"esearch response was not valid JSON: {exc}") from exc
        search = data.get("esearchresult", {})
        pmids = list(search.get("idlist", []))
        try:
            total = int(search.get("count", 0))
        except (TypeError, ValueError) as exc:
            raise PubMedParseError(
                f"esearch returned non-integer count: {search.get('count')!r}"
            ) from exc
        return ESearchResult(
            query=query,
            pmids=pmids,
            total_count=total,
            returned_count=len(pmids),
        )

    def _do_count(self, query: str) -> int:
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": 0,
            "retmode": "json",
            "usehistory": "n",
        }
        resp = self._get("esearch.fcgi", params)
        try:
            data = resp.json()
        except ValueError as exc:
            raise PubMedParseError(f"count response was not valid JSON: {exc}") from exc
        try:
            return int(data.get("esearchresult", {}).get("count", 0))
        except (TypeError, ValueError) as exc:
            raise PubMedParseError(f"non-integer count: {exc}") from exc

    def _do_fetch(self, pmids: list[str]) -> list[dict]:
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "rettype": "abstract",
            "retmode": "xml",
        }
        resp = self._get("efetch.fcgi", params)
        return self._parse_xml(resp.text)

    # ------------------------------------------------------------------
    # XML parsing
    # ------------------------------------------------------------------

    def _parse_xml(self, xml_text: str) -> list[dict]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise PubMedParseError(f"efetch XML parse failed: {exc}") from exc

        records: list[dict] = []
        for article_el in root.findall(".//PubmedArticle"):
            try:
                record = self._parse_article(article_el)
                if record is not None:
                    records.append(record)
            except Exception as exc:  # never drop the whole batch for one bad record
                pmid_el = article_el.find(".//PMID")
                pmid_hint = pmid_el.text if pmid_el is not None else "unknown"
                logger.warning(
                    "Skipping malformed PubMed article PMID=%s: %s", pmid_hint, exc
                )
        return records

    def _parse_article(self, el: ET.Element) -> Optional[dict]:
        pmid_el = el.find(".//MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            return None
        pmid = pmid_el.text.strip()

        title_el = el.find(".//Article/ArticleTitle")
        title = _stringify(title_el)

        abstract = self._parse_abstract(el)

        pub_types: list[str] = []
        for pt_el in el.findall(".//PublicationTypeList/PublicationType"):
            if pt_el.text:
                pub_types.append(pt_el.text)
        # Retraction notices: flag the retracted paper via its pub-types.
        if el.find(".//CommentsCorrections[@RefType='RetractionIn']") is not None:
            if "Retracted Publication" not in pub_types:
                pub_types.append("Retracted Publication")

        journal_el = el.find(".//Article/Journal/Title")
        journal = _stringify(journal_el)

        year = _parse_year(el)

        authors: list[str] = []
        for author_el in el.findall(".//AuthorList/Author"):
            last = author_el.find("LastName")
            initials = author_el.find("Initials")
            if last is not None and last.text:
                name = last.text.strip()
                if initials is not None and initials.text:
                    name = f"{name} {initials.text.strip()}"
                authors.append(name)

        # Legacy extras — kept so Sharon's Paper dataclass still populates.
        mesh_terms: list[str] = [
            mh.text.strip()
            for mh in el.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
            if mh.text
        ]
        doi_el = el.find(".//ArticleId[@IdType='doi']")
        doi = doi_el.text.strip() if doi_el is not None and doi_el.text else None
        language_el = el.find(".//Article/Language")
        language = language_el.text.strip().lower() if language_el is not None and language_el.text else "eng"

        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "pub_types": pub_types,
            "journal": journal,
            "year": year,
            "authors": authors,
            # Legacy passthroughs:
            "mesh_terms": mesh_terms,
            "doi": doi,
            "language": language,
        }

    def _parse_abstract(self, el: ET.Element) -> str:
        """Concatenate labeled or unlabeled ``<AbstractText>`` blocks."""
        abstract_els = el.findall(".//Abstract/AbstractText")
        if not abstract_els:
            return ""
        parts: list[str] = []
        for ab in abstract_els:
            text = _stringify(ab)
            if not text:
                continue
            label = ab.get("Label") or ab.get("NlmCategory")
            if label:
                parts.append(f"{label}: {text}")
            else:
                parts.append(text)
        return "\n".join(parts)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stringify(el: Optional[ET.Element]) -> str:
    """Flatten an element with mixed inline markup (italic, sub, sup, etc.)."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _parse_year(el: ET.Element) -> Optional[int]:
    year_el = el.find(".//Article/Journal/JournalIssue/PubDate/Year")
    if year_el is not None and year_el.text:
        try:
            return int(year_el.text.strip()[:4])
        except ValueError:
            pass
    medline_el = el.find(".//Article/Journal/JournalIssue/PubDate/MedlineDate")
    if medline_el is not None and medline_el.text:
        match = re.search(r"\d{4}", medline_el.text)
        if match:
            return int(match.group())
    return None
