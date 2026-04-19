"""Tests for the rebuilt PubMed client (retrieval spec Task 1)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.retrieval.errors import (
    PubMedNetworkError,
    PubMedParseError,
    PubMedRateLimitError,
)
from src.retrieval.pubmed_client import PubMedClient, _RateLimiter
from src.retrieval.schemas import ESearchResult


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int, body: str | dict, headers: dict | None = None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    if isinstance(body, dict):
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.text = body
        resp.json.side_effect = lambda: json.loads(body)
    return resp


def _bare_session():
    """``MagicMock(spec=Session)`` omits instance attrs like ``headers``; add it."""
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    return session


def _mock_session(responses):
    """Build a mock ``requests.Session`` that yields ``responses`` in order."""
    session = _bare_session()
    if not isinstance(responses, (list, tuple)):
        responses = [responses]
    session.get.side_effect = list(responses)
    return session


def _client(session, *, cache=None, api_key=None):
    """Construct a client with a known session and cache, ignoring env vars."""
    with patch.dict("os.environ", {}, clear=True):
        return PubMedClient(api_key=api_key, cache=cache, session=session)


# ---------------------------------------------------------------------------
# esearch + count
# ---------------------------------------------------------------------------

def test_esearch_returns_pmids_and_total_count():
    session = _mock_session(
        _make_response(
            200,
            {"esearchresult": {"idlist": ["111", "222", "333"], "count": "42"}},
        )
    )
    client = _client(session)

    result = client.esearch("turmeric AND inflammation", max_results=3)

    assert isinstance(result, ESearchResult)
    assert result.query == "turmeric AND inflammation"
    assert result.pmids == ["111", "222", "333"]
    assert result.total_count == 42
    assert result.returned_count == 3


def test_count_returns_int():
    session = _mock_session(
        _make_response(200, {"esearchresult": {"idlist": [], "count": "1099"}})
    )
    client = _client(session)

    assert client.count("coffee AND pregnancy") == 1099


def test_esearch_invalid_json_raises_parse_error():
    bad = MagicMock(spec=requests.Response)
    bad.status_code = 200
    bad.headers = {}
    bad.text = "not json"
    bad.json.side_effect = ValueError("Expecting value")

    client = _client(_mock_session(bad))
    with pytest.raises(PubMedParseError):
        client.esearch("anything")


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

def test_retries_on_429_then_succeeds():
    rate_limit = _make_response(429, "", headers={"Retry-After": "0"})
    success = _make_response(
        200, {"esearchresult": {"idlist": ["5"], "count": "1"}}
    )
    session = _mock_session([rate_limit, success])
    client = _client(session)

    result = client.esearch("x")
    assert result.pmids == ["5"]
    assert session.get.call_count == 2


def test_retries_on_5xx_then_succeeds():
    server_err = _make_response(502, "")
    success = _make_response(
        200, {"esearchresult": {"idlist": [], "count": "0"}}
    )
    session = _mock_session([server_err, success])
    client = _client(session)

    client.esearch("x")
    assert session.get.call_count == 2


def test_4xx_does_not_retry_and_raises_network_error():
    session = _mock_session(_make_response(400, ""))
    client = _client(session)

    with pytest.raises(PubMedNetworkError) as exc:
        client.esearch("x")
    assert exc.value.status_code == 400
    assert session.get.call_count == 1


def test_429_gives_up_after_max_attempts():
    # Four 429s in a row -> should raise after all retries exhausted.
    rate_limit = _make_response(429, "", headers={"Retry-After": "0"})
    session = _mock_session([rate_limit] * 6)
    client = _client(session)

    with pytest.raises(PubMedRateLimitError):
        client.esearch("x")
    # Retry config: stop_after_attempt(4). Each wait_exponential uses real
    # sleep, but min=2s, so this test tolerates up to ~12s of waits.


def test_connection_error_is_retryable():
    success = _make_response(
        200, {"esearchresult": {"idlist": [], "count": "0"}}
    )
    session = _bare_session()
    session.headers = {}
    session.get.side_effect = [
        requests.ConnectionError("dns fail"),
        success,
    ]
    client = _client(session)

    client.esearch("x")
    assert session.get.call_count == 2


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def test_cache_prevents_duplicate_network_calls():
    response = _make_response(
        200, {"esearchresult": {"idlist": ["1"], "count": "1"}}
    )
    # Only ONE response queued — a second network call would raise StopIteration.
    session = _mock_session([response])
    cache: dict = {}
    client = _client(session, cache=cache)

    first = client.esearch("same query", max_results=5)
    second = client.esearch("same query", max_results=5)

    assert first.pmids == second.pmids == ["1"]
    assert session.get.call_count == 1
    assert len(cache) == 1


def test_cache_miss_on_different_args():
    r1 = _make_response(200, {"esearchresult": {"idlist": ["1"], "count": "1"}})
    r2 = _make_response(200, {"esearchresult": {"idlist": ["2"], "count": "2"}})
    session = _mock_session([r1, r2])
    client = _client(session, cache={})

    client.esearch("q", max_results=5)
    client.esearch("q", max_results=10)   # different max_results -> miss
    assert session.get.call_count == 2


def test_no_cache_when_cache_is_none():
    r = _make_response(200, {"esearchresult": {"idlist": ["1"], "count": "1"}})
    session = _mock_session([r, r])
    client = _client(session, cache=None)

    client.esearch("q")
    client.esearch("q")
    assert session.get.call_count == 2


# ---------------------------------------------------------------------------
# XML parsing (fetch_details + abstract structures)
# ---------------------------------------------------------------------------

_UNLABELED_ABSTRACT_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>1001</PMID>
      <Article>
        <ArticleTitle>Curcumin and inflammation</ArticleTitle>
        <Abstract>
          <AbstractText>Curcumin reduces inflammatory markers in arthritis.</AbstractText>
        </Abstract>
        <Journal>
          <Title>Some Journal</Title>
          <JournalIssue>
            <PubDate><Year>2024</Year></PubDate>
          </JournalIssue>
        </Journal>
        <Language>eng</Language>
      </Article>
      <AuthorList>
        <Author><LastName>Smith</LastName><Initials>J</Initials></Author>
      </AuthorList>
      <PublicationTypeList>
        <PublicationType>Journal Article</PublicationType>
      </PublicationTypeList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


_LABELED_ABSTRACT_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>2002</PMID>
      <Article>
        <ArticleTitle>A structured trial</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Curcumin has anti-inflammatory properties.</AbstractText>
          <AbstractText Label="METHODS">Double-blind RCT, 120 patients.</AbstractText>
          <AbstractText Label="RESULTS">Significant reduction in IL-6.</AbstractText>
          <AbstractText Label="CONCLUSIONS">Curcumin reduces systemic inflammation.</AbstractText>
        </Abstract>
        <Journal>
          <Title>Trial Journal</Title>
          <JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue>
        </Journal>
      </Article>
      <PublicationTypeList>
        <PublicationType>Randomized Controlled Trial</PublicationType>
      </PublicationTypeList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


_RETRACTED_ARTICLE_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>3003</PMID>
      <Article>
        <ArticleTitle>Disputed paper</ArticleTitle>
        <Abstract><AbstractText>Short abstract.</AbstractText></Abstract>
        <Journal><Title>J</Title><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
      </Article>
      <PublicationTypeList>
        <PublicationType>Journal Article</PublicationType>
      </PublicationTypeList>
      <CommentsCorrectionsList>
        <CommentsCorrections RefType="RetractionIn"><RefSource>src</RefSource></CommentsCorrections>
      </CommentsCorrectionsList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_fetch_details_parses_unlabeled_abstract():
    session = _mock_session(_make_response(200, _UNLABELED_ABSTRACT_XML))
    client = _client(session)

    records = client.fetch_details(["1001"])
    assert len(records) == 1
    r = records[0]
    assert r["pmid"] == "1001"
    assert r["title"] == "Curcumin and inflammation"
    assert r["abstract"] == "Curcumin reduces inflammatory markers in arthritis."
    assert r["pub_types"] == ["Journal Article"]
    assert r["journal"] == "Some Journal"
    assert r["year"] == 2024
    assert r["authors"] == ["Smith J"]


def test_fetch_details_parses_labeled_abstract_with_newlines():
    session = _mock_session(_make_response(200, _LABELED_ABSTRACT_XML))
    client = _client(session)

    records = client.fetch_details(["2002"])
    abstract = records[0]["abstract"]
    # Labeled sections are joined by newlines.
    assert "BACKGROUND: Curcumin has anti-inflammatory properties." in abstract
    assert "METHODS: Double-blind RCT, 120 patients." in abstract
    assert "RESULTS: Significant reduction in IL-6." in abstract
    assert "CONCLUSIONS: Curcumin reduces systemic inflammation." in abstract
    assert abstract.count("\n") == 3


def test_fetch_details_handles_empty_pmid_list_without_network():
    session = _bare_session()
    session.headers = {}
    client = _client(session)
    assert client.fetch_details([]) == []
    assert session.get.call_count == 0


def test_fetch_details_batches_200_at_a_time():
    # 201 PMIDs should trigger 2 efetch calls.
    xml = _UNLABELED_ABSTRACT_XML
    session = _mock_session([_make_response(200, xml), _make_response(200, xml)])
    client = _client(session)

    client.fetch_details([str(i) for i in range(201)])
    assert session.get.call_count == 2


def test_fetch_details_xml_parse_error_is_typed():
    bad_xml = "<<<not valid xml"
    session = _mock_session(_make_response(200, bad_xml))
    client = _client(session)

    with pytest.raises(PubMedParseError):
        client.fetch_details(["99"])


# ---------------------------------------------------------------------------
# check_retractions
# ---------------------------------------------------------------------------

def test_check_retractions_flags_retracted_publication_type():
    session = _mock_session(_make_response(200, _RETRACTED_ARTICLE_XML))
    client = _client(session)
    assert client.check_retractions(["3003"]) == {"3003"}


def test_check_retractions_empty_for_non_retracted_paper():
    session = _mock_session(_make_response(200, _UNLABELED_ABSTRACT_XML))
    client = _client(session)
    assert client.check_retractions(["1001"]) == set()


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

def test_rate_limiter_waits_for_min_interval():
    limiter = _RateLimiter(min_interval=0.5)
    clock = [1.0]
    sleeps: list[float] = []

    def fake_now():
        return clock[0]

    def fake_sleep(s):
        sleeps.append(s)
        clock[0] += s

    # First call: no prior request, no sleep.
    limiter.wait(now_fn=fake_now, sleep_fn=fake_sleep)
    assert sleeps == []

    # 0.1s later: must sleep 0.4s to reach the 0.5s interval.
    clock[0] += 0.1
    limiter.wait(now_fn=fake_now, sleep_fn=fake_sleep)
    assert sleeps == [pytest.approx(0.4)]


def test_rate_limiter_does_not_wait_if_interval_already_elapsed():
    limiter = _RateLimiter(min_interval=0.1)
    clock = [10.0]  # start well past _last=0.0 so the first call skips sleep
    sleeps: list[float] = []

    limiter.wait(now_fn=lambda: clock[0], sleep_fn=sleeps.append)
    clock[0] = 20.0
    limiter.wait(now_fn=lambda: clock[0], sleep_fn=sleeps.append)
    assert sleeps == []


def test_client_with_key_uses_faster_rate():
    with patch.dict("os.environ", {}, clear=True):
        fast = PubMedClient(api_key="fake", session=_bare_session())
        slow = PubMedClient(session=_bare_session())
    assert fast._limiter._interval < slow._limiter._interval


# ---------------------------------------------------------------------------
# Env-var handling
# ---------------------------------------------------------------------------

def test_api_key_picked_from_pubmed_env_var():
    with patch.dict("os.environ", {"PUBMED_API_KEY": "via-env"}, clear=True):
        c = PubMedClient(session=_bare_session())
    assert c.api_key == "via-env"


def test_api_key_falls_back_to_ncbi_env_var():
    with patch.dict("os.environ", {"NCBI_API_KEY": "via-ncbi"}, clear=True):
        c = PubMedClient(session=_bare_session())
    assert c.api_key == "via-ncbi"


def test_explicit_api_key_wins_over_env():
    with patch.dict("os.environ", {"PUBMED_API_KEY": "env"}, clear=True):
        c = PubMedClient(api_key="explicit", session=_bare_session())
    assert c.api_key == "explicit"


# ---------------------------------------------------------------------------
# API key is sent on the wire
# ---------------------------------------------------------------------------

def test_api_key_is_added_to_request_params():
    session = _mock_session(
        _make_response(200, {"esearchresult": {"idlist": [], "count": "0"}})
    )
    client = _client(session, api_key="my-key")
    client.esearch("x")

    _, kwargs = session.get.call_args
    assert kwargs["params"]["api_key"] == "my-key"


def test_no_api_key_param_when_none_set():
    session = _mock_session(
        _make_response(200, {"esearchresult": {"idlist": [], "count": "0"}})
    )
    client = _client(session, api_key=None)
    client.esearch("x")

    _, kwargs = session.get.call_args
    assert "api_key" not in kwargs["params"]


