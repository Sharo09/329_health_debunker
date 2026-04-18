"""Shared retry wrapper for Gemini calls on the free tier.

The free tier's per-minute quota (5 req/min on gemini-2.5-flash) means
any multi-step agent blows through in seconds. google-genai's internal
``tenacity`` retry doesn't honour the ``Retry-After`` hint on 429, so
we add a thin wrapper that:

  * catches ``google.genai.errors.ClientError``
  * if status is 429, extracts ``retryDelay`` from the error body
    (falls back to a sensible default) and sleeps
  * retries up to ``max_attempts`` times, then re-raises

This pattern is cheap and makes demos usable on the free tier at the
cost of wall time (~2-4 minutes per demo on Flash free tier).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_SLEEP = 65  # seconds — cover Gemini's worst-case minute-reset window


def call_with_429_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 4,
    default_sleep: float = 15.0,
) -> T:
    """Call ``fn`` and retry on 429 RESOURCE_EXHAUSTED.

    Google's ``genai.errors.ClientError`` carries a status code and a
    JSON-ish error body. We parse ``retryDelay`` out of the body and
    sleep that long (capped at ``_MAX_SLEEP``). On other HTTP errors,
    the exception is re-raised immediately — they aren't rate-limit
    issues.
    """
    try:
        from google.genai.errors import ClientError
    except ImportError:  # pragma: no cover — google-genai required in prod
        return fn()

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except ClientError as exc:
            last_exc = exc
            status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            if status != 429:
                raise
            if attempt == max_attempts - 1:
                break  # exhausted — re-raise below
            sleep_s = _extract_retry_delay(exc, default_sleep)
            logger.warning(
                "Gemini 429 on attempt %d/%d; sleeping %.1fs before retry.",
                attempt + 1,
                max_attempts,
                sleep_s,
            )
            time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RETRY_DELAY_PATTERNS = [
    re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s"),
    re.compile(r"retry in (\d+(?:\.\d+)?)s"),
]


def _extract_retry_delay(exc: Exception, default: float) -> float:
    text = str(exc)
    for pat in _RETRY_DELAY_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                return min(float(m.group(1)) + 1.0, _MAX_SLEEP)
            except ValueError:
                pass
    return min(default, _MAX_SLEEP)
