"""Tests for RetrievalCache — retrieval spec Task 8."""

from __future__ import annotations

import pytest

from src.retrieval.cache import RetrievalCache
from src.retrieval.pubmed_client import PubMedClient


def test_cache_creates_three_named_subcaches(tmp_path):
    cache = RetrievalCache(path=str(tmp_path / "cache"))
    try:
        assert cache.pubmed is not None
        assert cache.llm is not None
        assert cache.caers is not None
        # Each sits in its own directory.
        assert (tmp_path / "cache" / "pubmed").is_dir()
        assert (tmp_path / "cache" / "llm").is_dir()
        assert (tmp_path / "cache" / "caers").is_dir()
    finally:
        cache.close()


def test_cache_integrates_with_pubmed_client(tmp_path):
    """The cache must drop straight into PubMedClient(cache=...) and survive a second instance."""
    from unittest.mock import MagicMock

    import requests

    cache = RetrievalCache(path=str(tmp_path / "cache"))
    try:
        session = MagicMock(spec=requests.Session)
        session.headers = {}
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {"esearchresult": {"idlist": ["1"], "count": "1"}}
        session.get.return_value = resp

        # Two clients sharing the same diskcache; the second one must hit the cache.
        client1 = PubMedClient(cache=cache.pubmed, session=session)
        client1.esearch("turmeric", max_results=5)
        assert session.get.call_count == 1

        session.get.reset_mock()
        session2 = MagicMock(spec=requests.Session)
        session2.headers = {}
        session2.get.side_effect = AssertionError("cache should have served this")

        client2 = PubMedClient(cache=cache.pubmed, session=session2)
        result = client2.esearch("turmeric", max_results=5)
        assert result.pmids == ["1"]
        assert session2.get.call_count == 0
    finally:
        cache.close()


def test_cache_clear_empties_every_subcache(tmp_path):
    cache = RetrievalCache(path=str(tmp_path / "cache"))
    try:
        cache.pubmed["x"] = 1
        cache.llm["y"] = 2
        cache.caers["z"] = 3
        cache.clear()
        assert "x" not in cache.pubmed
        assert "y" not in cache.llm
        assert "z" not in cache.caers
    finally:
        cache.close()


def test_cache_works_as_context_manager(tmp_path):
    path = str(tmp_path / "cache")
    with RetrievalCache(path=path) as cache:
        cache.pubmed["a"] = 1
        assert cache.pubmed["a"] == 1
    # After __exit__ the subcaches are closed; reopening works.
    cache2 = RetrievalCache(path=path)
    try:
        assert cache2.pubmed["a"] == 1
    finally:
        cache2.close()
