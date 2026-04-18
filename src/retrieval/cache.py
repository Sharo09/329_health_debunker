"""Disk-backed caches for retrieval (retrieval spec Task 8).

Three separate ``diskcache.Cache`` instances live under one directory:

    .cache/retrieval/
        pubmed/   — PubMed esearch/efetch responses        (~500 MB cap)
        llm/      — LLM completion responses                (~200 MB cap)
        caers/    — openFDA CAERS responses                 (~100 MB cap)

All three implement the ``MutableMapping`` interface and drop straight
into the ``cache=`` parameter of the respective clients.

No TTL — results are stable for the lifetime of the demo. Production
would want a ~30-day TTL, but that can come later.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

try:
    from diskcache import Cache as _DiskCache
except ImportError:  # pragma: no cover
    _DiskCache = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_CACHE_ROOT = ".cache/retrieval"

# Size limits in bytes.
PUBMED_SIZE_LIMIT = 500 * 1024 * 1024
LLM_SIZE_LIMIT = 200 * 1024 * 1024
CAERS_SIZE_LIMIT = 100 * 1024 * 1024


class RetrievalCache:
    """Bundle of three caches. Lazy per-subcache initialisation."""

    def __init__(self, path: str = DEFAULT_CACHE_ROOT):
        if _DiskCache is None:
            raise ImportError(
                "diskcache is not installed. `pip install diskcache` to enable "
                "persistent caching; otherwise pass cache=None explicitly."
            )
        self.path = path
        os.makedirs(path, exist_ok=True)
        self.pubmed = _DiskCache(os.path.join(path, "pubmed"), size_limit=PUBMED_SIZE_LIMIT)
        self.llm = _DiskCache(os.path.join(path, "llm"), size_limit=LLM_SIZE_LIMIT)
        self.caers = _DiskCache(os.path.join(path, "caers"), size_limit=CAERS_SIZE_LIMIT)

    def close(self) -> None:
        for c in (self.pubmed, self.llm, self.caers):
            try:
                c.close()
            except Exception as exc:
                logger.debug("Cache close failed: %s", exc)

    def clear(self) -> None:
        """Drop every cached entry. Use with care."""
        for c in (self.pubmed, self.llm, self.caers):
            try:
                c.clear()
            except Exception as exc:
                logger.debug("Cache clear failed: %s", exc)

    # Context-manager sugar so callers can do::
    #
    #     with RetrievalCache() as caches:
    #         client = PubMedClient(cache=caches.pubmed)
    #         ...
    def __enter__(self) -> "RetrievalCache":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
