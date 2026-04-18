"""openFDA CAERS (food adverse-event) client for Station 3.

Wraps a single endpoint: ``https://api.fda.gov/food/event.json``.

openFDA quirks worth knowing
----------------------------
- **404 means "no matching records"**, not a real error. The client
  translates that into an empty list so callers don't have to special-case.
- **Search syntax is Lucene-ish.** Space / ``+`` = AND, ``+OR+`` = OR.
  To search across both ``products.name_brand`` and
  ``products.industry_name`` we use an explicit OR block.
- **Dates are ``YYYYMMDD`` strings**, not ISO. We convert to
  ``YYYY-MM-DD`` when populating ``CAERSReport``.
- **Rate limits**: 40 req/min anonymous, 240 req/min with an API key
  (free — https://open.fda.gov/apis/authentication/).

This client is deliberately small. All "intelligence" (matching food
names, deciding what to do with the reports) lives upstream in the
retrieval agent and downstream in Station 4. We just query and parse.
"""

from __future__ import annotations

import logging
import os
import time
from threading import Lock
from typing import Any, MutableMapping, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.retrieval.errors import CAERSAPIError
from src.retrieval.schemas import CAERSReport

logger = logging.getLogger(__name__)

BASE_URL = "https://api.fda.gov/food/event.json"

# 40 req/min anonymous -> 1.5s between calls (conservative).
# 240 req/min with key -> 0.25s between calls.
_DELAY_ANON = 1.5
_DELAY_WITH_KEY = 0.25


# ---------------------------------------------------------------------------
# Rate limiter (mirrors pubmed_client.py)
# ---------------------------------------------------------------------------

class _RateLimiter:
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


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, CAERSAPIError):
        if exc.status_code is None:
            return True
        if exc.status_code == 429:
            return True
        if 500 <= exc.status_code < 600:
            return True
    return False


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class CAERSClient:
    """Thin, robust wrapper around the openFDA food-event endpoint."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[MutableMapping[str, Any]] = None,
        session: Optional[requests.Session] = None,
    ):
        self.api_key = api_key or os.getenv("OPENFDA_API_KEY")
        self._limiter = _RateLimiter(
            _DELAY_WITH_KEY if self.api_key else _DELAY_ANON
        )
        self._cache = cache
        self._session = session or requests.Session()
        self._session.headers.setdefault(
            "User-Agent", "HealthMythDebunker/1.0 (academic research)"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_by_product(
        self,
        product_term: str,
        since_year: int = 2018,
        limit: int = 100,
    ) -> list[CAERSReport]:
        """Search CAERS by product/ingredient term.

        Matches ``products.name_brand`` OR ``products.industry_name``.
        Filters to reports whose ``date_created`` is on or after
        ``YYYY-01-01`` of ``since_year``.

        Returns an empty list (not an exception) when openFDA has no
        matching records.
        """
        if not product_term or not product_term.strip():
            return []

        search = self._build_search(product_term, since_year)
        key = f"search::{since_year}::{limit}::{product_term.strip().lower()}"
        raw = self._cached(key, lambda: self._fetch(search, limit=limit))
        if raw is None:
            return []
        return [self._to_report(r) for r in raw.get("results", [])]

    def count_by_reaction(self, product_term: str) -> dict[str, int]:
        """Return a dict mapping reaction preferred terms to counts.

        Uses openFDA's built-in ``count=reactions.exact`` aggregation.
        Cheap — one request regardless of report volume.
        """
        if not product_term or not product_term.strip():
            return {}

        search = self._build_search(product_term, since_year=None)
        key = f"count::{product_term.strip().lower()}"
        raw = self._cached(
            key, lambda: self._fetch(search, count_field="reactions.exact")
        )
        if raw is None:
            return {}
        out: dict[str, int] = {}
        for row in raw.get("results", []):
            term = row.get("term")
            count = row.get("count")
            if term and isinstance(count, int):
                out[term] = count
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_search(
        self, product_term: str, since_year: Optional[int]
    ) -> str:
        """Construct an openFDA ``search`` parameter string."""
        term = _escape(product_term.strip())
        product_clause = (
            f'(products.name_brand:"{term}" OR products.industry_name:"{term}")'
        )
        if since_year is None:
            return product_clause
        # openFDA uses YYYYMMDD, inclusive on both ends.
        from_date = f"{since_year}0101"
        return f"{product_clause} AND date_created:[{from_date} TO 99991231]"

    def _cached(self, key: str, compute):
        if self._cache is None:
            return compute()
        if key in self._cache:
            return self._cache[key]
        value = compute()
        try:
            self._cache[key] = value
        except Exception as exc:
            logger.debug("CAERS cache write failed for %r: %s", key, exc)
        return value

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _fetch(
        self,
        search: str,
        *,
        limit: Optional[int] = None,
        count_field: Optional[str] = None,
    ) -> Optional[dict]:
        """Do one HTTP GET. Returns the JSON body, or ``None`` on 404."""
        self._limiter.wait()
        params: dict[str, Any] = {"search": search}
        if count_field is not None:
            params["count"] = count_field
        if limit is not None:
            params["limit"] = limit
        if self.api_key:
            params["api_key"] = self.api_key
        try:
            resp = self._session.get(BASE_URL, params=params, timeout=30)
        except requests.ConnectionError as exc:
            raise CAERSAPIError(f"Connection error: {exc}") from exc
        except requests.Timeout as exc:
            raise CAERSAPIError(f"Timeout: {exc}") from exc

        if resp.status_code == 404:
            # openFDA returns 404 for "no hits". Treat as empty, not error.
            return None
        if resp.status_code != 200:
            if resp.status_code == 429 or resp.status_code >= 500:
                raise CAERSAPIError(
                    f"openFDA returned {resp.status_code}", status_code=resp.status_code
                )
            raise CAERSAPIError(
                f"openFDA returned {resp.status_code}", status_code=resp.status_code
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise CAERSAPIError(f"openFDA response was not valid JSON: {exc}") from exc

    def _to_report(self, raw: dict) -> CAERSReport:
        """Map one raw openFDA record to a ``CAERSReport``."""
        products = raw.get("products") or []
        first = products[0] if products else {}

        reactions = [
            r for r in (raw.get("reactions") or []) if isinstance(r, str)
        ]
        outcomes = [
            o for o in (raw.get("outcomes") or []) if isinstance(o, str)
        ]

        return CAERSReport(
            report_id=str(raw.get("report_number", "")),
            date=_iso_date(raw.get("date_created")),
            product_name=first.get("name_brand", "") or "",
            industry_name=first.get("industry_name", "") or "",
            reactions=reactions,
            outcomes=outcomes,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape(term: str) -> str:
    """Escape Lucene specials that would break openFDA's search grammar."""
    # openFDA accepts backslash-escapes. Escape the ones most likely to appear
    # in consumer-typed product names.
    return term.replace("\\", "\\\\").replace('"', '\\"')


def _iso_date(raw: Optional[str]) -> str:
    """Convert openFDA's ``YYYYMMDD`` to ISO ``YYYY-MM-DD``.

    Returns an empty string when the input is missing or malformed so
    downstream code never crashes on a bad date.
    """
    if not raw or len(raw) != 8 or not raw.isdigit():
        return ""
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
