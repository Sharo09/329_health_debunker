"""Tests for the CAERS (openFDA food/event) client — retrieval spec Task 2."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.retrieval.caers_client import BASE_URL, CAERSClient, _iso_date
from src.retrieval.errors import CAERSAPIError
from src.retrieval.schemas import CAERSReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bare_session():
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    return session


def _response(status_code: int, body: dict | str | None = None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = {}
    if isinstance(body, dict):
        resp.json.return_value = body
        resp.text = json.dumps(body)
    elif isinstance(body, str):
        resp.text = body
        resp.json.side_effect = ValueError("not json")
    else:
        resp.text = ""
        resp.json.side_effect = ValueError("not json")
    return resp


def _client(session, **kwargs):
    with patch.dict("os.environ", {}, clear=True):
        return CAERSClient(session=session, **kwargs)


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

SAMPLE_REPORT = {
    "report_number": "123456",
    "date_created": "20230405",
    "outcomes": ["Hospitalization", "Other serious"],
    "reactions": ["Nausea", "Vomiting"],
    "products": [
        {
            "name_brand": "Super Turmeric Extract",
            "industry_name": "Vit/Min/Prot/Unconv Diet(Human/Animal)",
            "role": "Suspect",
        },
        {
            "name_brand": "Daily Multivitamin",
            "industry_name": "Vit/Min/Prot/Unconv Diet(Human/Animal)",
            "role": "Concomitant",
        },
    ],
}

SAMPLE_SEARCH_BODY = {
    "meta": {"results": {"skip": 0, "limit": 100, "total": 2}},
    "results": [SAMPLE_REPORT, {**SAMPLE_REPORT, "report_number": "123457"}],
}

SAMPLE_COUNT_BODY = {
    "meta": {"results": {"skip": 0, "limit": 1000, "total": 3}},
    "results": [
        {"term": "Nausea", "count": 42},
        {"term": "Vomiting", "count": 38},
        {"term": "Hepatic enzyme increased", "count": 9},
    ],
}


# ---------------------------------------------------------------------------
# search_by_product
# ---------------------------------------------------------------------------

def test_search_parses_reports_correctly():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    reports = _client(session).search_by_product("turmeric")

    assert len(reports) == 2
    r = reports[0]
    assert isinstance(r, CAERSReport)
    assert r.report_id == "123456"
    assert r.date == "2023-04-05"     # ISO conversion
    assert r.product_name == "Super Turmeric Extract"   # first suspect product
    assert r.industry_name.startswith("Vit/Min")
    assert r.reactions == ["Nausea", "Vomiting"]
    assert r.outcomes == ["Hospitalization", "Other serious"]


def test_search_empty_term_returns_empty_without_network():
    session = _bare_session()
    assert _client(session).search_by_product("") == []
    assert _client(session).search_by_product("   ") == []
    assert session.get.call_count == 0


def test_search_404_is_graceful_empty_list():
    """openFDA returns 404 for "no matching records" — that's not a real error."""
    session = _bare_session()
    session.get.return_value = _response(404)
    assert _client(session).search_by_product("obscuretermx123") == []


def test_search_applies_since_year_date_filter():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    _client(session).search_by_product("coffee", since_year=2020)

    _, kwargs = session.get.call_args
    search_clause = kwargs["params"]["search"]
    assert "date_created:[20200101 TO 99991231]" in search_clause


def test_search_default_since_year_is_2018():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    _client(session).search_by_product("coffee")

    _, kwargs = session.get.call_args
    assert "date_created:[20180101 TO" in kwargs["params"]["search"]


def test_search_queries_both_product_and_industry_fields():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    _client(session).search_by_product("turmeric")

    _, kwargs = session.get.call_args
    search = kwargs["params"]["search"]
    assert 'products.name_brand:"turmeric"' in search
    assert 'products.industry_name:"turmeric"' in search
    assert " OR " in search


def test_search_respects_limit_parameter():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    _client(session).search_by_product("turmeric", limit=25)

    _, kwargs = session.get.call_args
    assert kwargs["params"]["limit"] == 25


def test_search_hits_the_right_endpoint():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    _client(session).search_by_product("turmeric")

    args, _ = session.get.call_args
    assert args[0] == BASE_URL


def test_search_escapes_quotes_in_term():
    session = _bare_session()
    session.get.return_value = _response(200, {"results": []})
    _client(session).search_by_product('risky"term')

    _, kwargs = session.get.call_args
    # Quote must be backslash-escaped so it doesn't break Lucene grammar.
    assert '\\"' in kwargs["params"]["search"]


def test_search_handles_missing_products_gracefully():
    """Some CAERS reports have no ``products`` array — don't crash."""
    body = {
        "results": [
            {
                "report_number": "999",
                "date_created": "20220101",
                "reactions": ["Dizziness"],
                "outcomes": [],
                # no "products" key
            }
        ]
    }
    session = _bare_session()
    session.get.return_value = _response(200, body)
    reports = _client(session).search_by_product("anything")
    assert reports[0].product_name == ""
    assert reports[0].industry_name == ""


def test_search_skips_non_string_reactions():
    body = {
        "results": [
            {
                "report_number": "1",
                "date_created": "20230101",
                "products": [{"name_brand": "X", "industry_name": "Y"}],
                "reactions": ["Nausea", None, 42, "Headache"],
                "outcomes": ["Hospitalization"],
            }
        ]
    }
    session = _bare_session()
    session.get.return_value = _response(200, body)
    reports = _client(session).search_by_product("x")
    assert reports[0].reactions == ["Nausea", "Headache"]


def test_search_malformed_date_leaves_iso_field_empty():
    body = {
        "results": [
            {
                "report_number": "1",
                "date_created": "not-a-date",
                "products": [{"name_brand": "X", "industry_name": "Y"}],
                "reactions": [],
                "outcomes": [],
            }
        ]
    }
    session = _bare_session()
    session.get.return_value = _response(200, body)
    reports = _client(session).search_by_product("x")
    assert reports[0].date == ""


# ---------------------------------------------------------------------------
# count_by_reaction
# ---------------------------------------------------------------------------

def test_count_by_reaction_parses_aggregation():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_COUNT_BODY)
    counts = _client(session).count_by_reaction("turmeric")

    assert counts == {
        "Nausea": 42,
        "Vomiting": 38,
        "Hepatic enzyme increased": 9,
    }


def test_count_uses_reactions_exact_aggregation():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_COUNT_BODY)
    _client(session).count_by_reaction("turmeric")

    _, kwargs = session.get.call_args
    assert kwargs["params"]["count"] == "reactions.exact"


def test_count_does_not_apply_date_filter():
    # ``count_by_reaction`` is a historical aggregation; year filter would
    # skew the headline counts users want to see.
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_COUNT_BODY)
    _client(session).count_by_reaction("turmeric")

    _, kwargs = session.get.call_args
    assert "date_created" not in kwargs["params"]["search"]


def test_count_404_returns_empty_dict():
    session = _bare_session()
    session.get.return_value = _response(404)
    assert _client(session).count_by_reaction("nothing") == {}


def test_count_empty_term_returns_empty_without_network():
    session = _bare_session()
    assert _client(session).count_by_reaction("") == {}
    assert session.get.call_count == 0


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

def test_retries_on_429_then_succeeds():
    session = _bare_session()
    session.get.side_effect = [
        _response(429),
        _response(200, SAMPLE_SEARCH_BODY),
    ]
    reports = _client(session).search_by_product("turmeric")
    assert len(reports) == 2
    assert session.get.call_count == 2


def test_retries_on_5xx_then_succeeds():
    session = _bare_session()
    session.get.side_effect = [
        _response(502),
        _response(200, SAMPLE_SEARCH_BODY),
    ]
    _client(session).search_by_product("turmeric")
    assert session.get.call_count == 2


def test_4xx_not_retryable_raises():
    session = _bare_session()
    session.get.return_value = _response(400)
    with pytest.raises(CAERSAPIError) as exc:
        _client(session).search_by_product("turmeric")
    assert exc.value.status_code == 400
    assert session.get.call_count == 1


def test_connection_error_is_retryable():
    session = _bare_session()
    session.get.side_effect = [
        requests.ConnectionError("dns fail"),
        _response(200, SAMPLE_SEARCH_BODY),
    ]
    _client(session).search_by_product("turmeric")
    assert session.get.call_count == 2


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def test_cache_prevents_duplicate_calls():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    cache: dict = {}
    client = _client(session, cache=cache)

    client.search_by_product("turmeric")
    client.search_by_product("turmeric")   # cache hit
    assert session.get.call_count == 1
    assert len(cache) == 1


def test_cache_miss_on_different_since_year():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    client = _client(session, cache={})

    client.search_by_product("turmeric", since_year=2018)
    client.search_by_product("turmeric", since_year=2022)
    assert session.get.call_count == 2


def test_no_cache_when_cache_is_none():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    client = _client(session, cache=None)

    client.search_by_product("turmeric")
    client.search_by_product("turmeric")
    assert session.get.call_count == 2


# ---------------------------------------------------------------------------
# API key handling
# ---------------------------------------------------------------------------

def test_api_key_picked_from_env():
    session = _bare_session()
    with patch.dict("os.environ", {"OPENFDA_API_KEY": "env-key"}, clear=True):
        c = CAERSClient(session=session)
    assert c.api_key == "env-key"


def test_explicit_api_key_wins_over_env():
    session = _bare_session()
    with patch.dict("os.environ", {"OPENFDA_API_KEY": "env"}, clear=True):
        c = CAERSClient(api_key="explicit", session=session)
    assert c.api_key == "explicit"


def test_api_key_sent_on_wire_when_set():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    with patch.dict("os.environ", {}, clear=True):
        CAERSClient(api_key="the-key", session=session).search_by_product("x")

    _, kwargs = session.get.call_args
    assert kwargs["params"]["api_key"] == "the-key"


def test_no_api_key_param_when_unset():
    session = _bare_session()
    session.get.return_value = _response(200, SAMPLE_SEARCH_BODY)
    _client(session).search_by_product("x")

    _, kwargs = session.get.call_args
    assert "api_key" not in kwargs["params"]


def test_client_with_key_uses_faster_rate():
    with patch.dict("os.environ", {}, clear=True):
        fast = CAERSClient(api_key="k", session=_bare_session())
        slow = CAERSClient(session=_bare_session())
    assert fast._limiter._interval < slow._limiter._interval


# ---------------------------------------------------------------------------
# Date conversion helper
# ---------------------------------------------------------------------------

def test_iso_date_converts_yyyymmdd():
    assert _iso_date("20240615") == "2024-06-15"


def test_iso_date_returns_empty_for_bad_input():
    assert _iso_date(None) == ""
    assert _iso_date("") == ""
    assert _iso_date("2024") == ""
    assert _iso_date("not-a-date") == ""
    assert _iso_date("2024abcd") == ""
