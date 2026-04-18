"""Tests for Station 3: Retrieval.

All PubMed API calls are mocked so tests run offline, deterministically,
and without any API cost.

Run with:
    pytest tests/test_retrieval.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.retrieval.errors import UnretrievableClaimError
from src.retrieval.pubmed_client import PubMedClient
from src.retrieval.query_builder import QueryBuilder, RelaxationLevel
from src.retrieval.retrieval_agent import RetrievalAgent
from src.retrieval.schemas import Paper, RetrievalResult
from src.schemas import LockedPICO   # real shared schema


# ===========================================================================
# Fixtures
# ===========================================================================

def make_locked_pico(**kwargs) -> LockedPICO:
    """Create a LockedPICO matching Station 2's real output format."""
    defaults = dict(
        raw_claim="Is turmeric good for inflammation?",
        food="turmeric",
        form="supplement",
        dose=None,
        frequency=None,
        population="healthy_adults",   # Station 2 stores underscores
        component=None,                # component was absent in the example
        outcome="inflammation",
        ambiguous_slots=["form", "dose", "frequency", "population", "component"],
        locked=True,
        conversation=[
            ["Are you asking about turmeric as food or as a supplement?",
             "As a curcumin supplement (standardized extract pills)"],
            ["Who is the question about?", "Healthy adults"],
        ],
        fallbacks_used=[],
    )
    defaults.update(kwargs)
    return LockedPICO(**defaults)


def make_paper(pmid: str = "11111111", title: str = "Test paper", abstract: str = "Test abstract.") -> Paper:
    return Paper(
        pmid=pmid, title=title, abstract=abstract,
        authors=["Smith J"], journal="Test Journal",
        pub_year=2022, pub_types=["Randomized Controlled Trial"],
        mesh_terms=["Curcumin", "Inflammation"],
    )


def stub_pubmed(pmids: list[str] = None, count: int = None) -> PubMedClient:
    """A mock PubMedClient that returns fixed data."""
    pmids = pmids or ["11111111", "22222222", "33333333",
                      "44444444", "55555555", "66666666",
                      "77777777", "88888888", "99999999", "10101010"]
    count = count if count is not None else len(pmids)
    client = MagicMock(spec=PubMedClient)
    client.search.return_value = (pmids, count)
    client.fetch.return_value = [make_paper(pmid=p) for p in pmids]
    return client


# ===========================================================================
# 1. QueryBuilder
# ===========================================================================

class TestQueryBuilder:
    def setup_method(self):
        self.builder = QueryBuilder()
        self.pico = make_locked_pico()

    def test_full_query_contains_food_terms(self):
        q = self.builder.build(self.pico, RelaxationLevel.FULL)
        assert "turmeric" in q.lower() or "curcumin" in q.lower()

    def test_full_query_contains_outcome(self):
        q = self.builder.build(self.pico, RelaxationLevel.FULL)
        assert "inflammation" in q.lower()

    def test_full_query_contains_form_terms(self):
        # form="supplement" should expand to supplement/capsule/extract terms
        q = self.builder.build(self.pico, RelaxationLevel.FULL)
        assert any(t in q.lower() for t in ["supplement", "capsule", "extract"])

    def test_full_query_contains_population_mesh(self):
        # population="healthy_adults" should map to adult[MeSH Terms]
        q = self.builder.build(self.pico, RelaxationLevel.FULL)
        assert "adult[MeSH Terms]".lower() in q.lower()

    def test_full_query_has_human_filter(self):
        q = self.builder.build(self.pico, RelaxationLevel.FULL)
        assert "humans[MeSH Terms]".lower() in q.lower()

    def test_drop_form_omits_form_terms(self):
        q = self.builder.build(self.pico, RelaxationLevel.DROP_FORM)
        assert "supplement[tiab]" not in q.lower()

    def test_core_omits_population_and_form(self):
        q = self.builder.build(self.pico, RelaxationLevel.CORE)
        assert "adult[MeSH Terms]".lower() not in q.lower()
        assert "supplement[tiab]" not in q.lower()

    def test_broad_is_shorter_than_full(self):
        q_full = self.builder.build(self.pico, RelaxationLevel.FULL)
        q_broad = self.builder.build(self.pico, RelaxationLevel.BROAD)
        assert len(q_broad) < len(q_full)

    def test_underscore_population_normalised(self):
        # "healthy_adults" (Station 2 format) must map to adult[MeSH Terms]
        pico = make_locked_pico(population="healthy_adults")
        q = self.builder.build(pico, RelaxationLevel.FULL)
        assert "adult[MeSH Terms]".lower() in q.lower()

    def test_unknown_food_uses_raw_name(self):
        pico = make_locked_pico(food="pomegranate", component=None)
        q = self.builder.build(pico, RelaxationLevel.FULL)
        assert "pomegranate" in q.lower()

    def test_known_food_expands_to_synonyms(self):
        pico = make_locked_pico(food="coffee", component=None)
        q = self.builder.build(pico, RelaxationLevel.FULL)
        assert "caffeine" in q.lower() or "coffea" in q.lower()

    def test_component_added_when_not_in_synonyms(self):
        # If Station 2 fills in component, it should appear in the query
        pico = make_locked_pico(food="turmeric", component="bisdemethoxycurcumin")
        q = self.builder.build(pico, RelaxationLevel.FULL)
        assert "bisdemethoxycurcumin" in q.lower()

    def test_none_food_and_none_outcome_raises(self):
        pico = make_locked_pico(food=None, outcome=None)
        with pytest.raises(ValueError):
            self.builder.build(pico, RelaxationLevel.FULL)

    def test_form_as_station2_display_text(self):
        # Station 2 may store the display label, not a short code
        pico = make_locked_pico(form="as a curcumin supplement (standardized extract pills)")
        q = self.builder.build(pico, RelaxationLevel.FULL)
        assert any(t in q.lower() for t in ["supplement", "curcumin", "extract"])


# ===========================================================================
# 2. PubMedClient XML Parsing
# ===========================================================================

SAMPLE_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">99887766</PMID>
      <Article>
        <ArticleTitle>Curcumin supplementation and <i>inflammation</i> in healthy adults</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Curcumin has anti-inflammatory properties.</AbstractText>
          <AbstractText Label="RESULTS">We observed significant reduction in IL-6.</AbstractText>
          <AbstractText Label="CONCLUSIONS">Curcumin supplementation reduces systemic inflammation.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Johnson</LastName><Initials>AB</Initials></Author>
        </AuthorList>
        <Language>eng</Language>
        <PublicationTypeList>
          <PublicationType>Randomized Controlled Trial</PublicationType>
        </PublicationTypeList>
        <Journal>
          <Title>Journal of Nutrition</Title>
          <JournalIssue><PubDate><Year>2023</Year></PubDate></JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1234/jn.2023.001</ArticleId>
        <ArticleId IdType="pubmed">99887766</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""


class TestPubMedClientParsing:
    """Tests for the XML parser. Updated for the Task 1 rebuild: the
    internal ``_parse_xml`` now returns dicts (per retrieval_spec.md),
    and malformed XML raises ``PubMedParseError`` instead of silently
    returning []. Public ``fetch()`` still returns ``Paper`` objects."""

    def setup_method(self):
        self.client = PubMedClient()

    def test_parses_pmid_title_abstract(self):
        records = self.client._parse_xml(SAMPLE_XML)
        assert len(records) == 1
        r = records[0]
        assert r["pmid"] == "99887766"
        assert "curcumin" in r["title"].lower()
        assert "BACKGROUND" in r["abstract"]

    def test_inline_markup_stripped_from_title(self):
        records = self.client._parse_xml(SAMPLE_XML)
        assert "<i>" not in records[0]["title"]

    def test_structured_abstract_joined(self):
        records = self.client._parse_xml(SAMPLE_XML)
        assert "RESULTS" in records[0]["abstract"]
        assert "CONCLUSIONS" in records[0]["abstract"]

    def test_pub_year_parsed(self):
        records = self.client._parse_xml(SAMPLE_XML)
        assert records[0]["year"] == 2023

    def test_doi_extracted(self):
        records = self.client._parse_xml(SAMPLE_XML)
        assert records[0]["doi"] == "10.1234/jn.2023.001"

    def test_not_retracted(self):
        records = self.client._parse_xml(SAMPLE_XML)
        assert "Retracted Publication" not in records[0]["pub_types"]

    def test_retracted_paper_flagged(self):
        xml = SAMPLE_XML.replace(
            "<PublicationType>Randomized Controlled Trial</PublicationType>",
            "<PublicationType>Retracted Publication</PublicationType>"
        )
        records = self.client._parse_xml(xml)
        assert "Retracted Publication" in records[0]["pub_types"]

    def test_empty_xml_returns_empty_list(self):
        assert self.client._parse_xml("<PubmedArticleSet></PubmedArticleSet>") == []

    def test_malformed_xml_raises_parse_error(self):
        from src.retrieval.errors import PubMedParseError
        with pytest.raises(PubMedParseError):
            self.client._parse_xml("not xml <<<")

    def test_missing_abstract_kept_with_empty_string(self):
        xml = SAMPLE_XML.replace("<Abstract>", "").replace("</Abstract>", "")
        records = self.client._parse_xml(xml)
        assert len(records) == 1
        assert records[0]["abstract"] == ""


# ===========================================================================
# 3. RetrievalAgent Integration
# ===========================================================================

class TestRetrievalAgent:

    def _agent(self, pubmed, **kwargs) -> RetrievalAgent:
        return RetrievalAgent(pubmed_client=pubmed, log_file="/tmp/test_retrieval.jsonl", **kwargs)

    def test_happy_path_returns_result(self):
        agent = self._agent(stub_pubmed())
        result = agent.retrieve(make_locked_pico())
        assert isinstance(result, RetrievalResult)
        assert len(result.papers) >= 1
        assert not result.below_threshold
        assert result.query_used != ""

    def test_both_food_and_outcome_missing_raises(self):
        agent = self._agent(stub_pubmed())
        with pytest.raises(UnretrievableClaimError):
            agent.retrieve(make_locked_pico(food=None, outcome=None))

    def test_relaxation_occurs_on_zero_hits(self):
        """FULL returns 0 hits; DROP_FORM returns results."""
        client = MagicMock(spec=PubMedClient)
        pmids = [str(i) for i in range(10)]
        client.search.side_effect = (
            [([], 0)] +              # FULL: empty
            [(pmids, 10)] * 10       # all subsequent levels: results
        )
        client.fetch.return_value = [make_paper(pmid=p) for p in pmids]
        agent = self._agent(client, min_threshold=5)
        result = agent.retrieve(make_locked_pico())
        assert result.relaxation_level > RelaxationLevel.FULL
        assert len(result.papers) > 0

    def test_below_threshold_flag_set(self):
        agent = self._agent(stub_pubmed(pmids=["1"], count=1), min_threshold=10)
        result = agent.retrieve(make_locked_pico())
        assert result.below_threshold

    def test_retracted_papers_kept_but_flagged(self):
        client = MagicMock(spec=PubMedClient)
        client.search.return_value = (["99"], 1)
        p = make_paper(pmid="99")
        p.is_retracted = True
        p.pub_types = ["Retraction of Publication"]
        client.fetch.return_value = [p]
        agent = self._agent(client, min_threshold=1)
        result = agent.retrieve(make_locked_pico())
        assert any(paper.is_retracted for paper in result.papers)

    def test_non_english_filtered_by_default(self):
        client = MagicMock(spec=PubMedClient)
        client.search.return_value = (["77"], 1)
        p = make_paper(pmid="77")
        p.language = "ger"
        client.fetch.return_value = [p]
        agent = self._agent(client, min_threshold=1)
        result = agent.retrieve(make_locked_pico())
        assert all(paper.language in ("eng", "en", "") for paper in result.papers)

    def test_non_english_kept_with_flag(self):
        client = MagicMock(spec=PubMedClient)
        client.search.return_value = (["77"], 1)
        p = make_paper(pmid="77")
        p.language = "ger"
        client.fetch.return_value = [p]
        agent = self._agent(client, min_threshold=1, keep_non_english=True)
        result = agent.retrieve(make_locked_pico())
        assert len(result.papers) == 1

    def test_paper_with_no_title_and_no_abstract_discarded(self):
        client = MagicMock(spec=PubMedClient)
        client.search.return_value = (["55"], 1)
        p = make_paper(pmid="55")
        p.title = ""
        p.abstract = ""
        client.fetch.return_value = [p]
        agent = self._agent(client, min_threshold=1)
        result = agent.retrieve(make_locked_pico())
        assert all(paper.title or paper.abstract for paper in result.papers)

    def test_audit_log_records_every_level_tried(self):
        client = MagicMock(spec=PubMedClient)
        client.search.side_effect = [
            ([], 0),                        # FULL
            ([str(i) for i in range(10)], 10),  # DROP_FORM
        ]
        client.fetch.return_value = [make_paper(pmid=str(i)) for i in range(10)]
        agent = self._agent(client, min_threshold=5)
        result = agent.retrieve(make_locked_pico())
        levels = [e.get("level") for e in result.audit_log if "level" in e]
        assert "FULL" in levels
        assert "DROP_FORM" in levels

    def test_soft_cap_limits_papers(self):
        pmids = [str(i) for i in range(50)]
        client = MagicMock(spec=PubMedClient)
        client.search.return_value = (pmids, 500)
        client.fetch.return_value = [make_paper(pmid=p) for p in pmids]
        agent = self._agent(client, soft_cap=15, min_threshold=5)
        result = agent.retrieve(make_locked_pico())
        assert len(result.papers) <= 15

    def test_all_levels_exhausted_returns_empty_result(self):
        client = MagicMock(spec=PubMedClient)
        client.search.return_value = ([], 0)
        client.fetch.return_value = []
        agent = self._agent(client)
        result = agent.retrieve(make_locked_pico())
        assert result.below_threshold
        assert result.papers == []

    def test_result_contains_locked_pico_query(self):
        agent = self._agent(stub_pubmed())
        result = agent.retrieve(make_locked_pico())
        assert "turmeric" in result.query_used.lower() or "curcumin" in result.query_used.lower()
        assert "inflammation" in result.query_used.lower()


# ===========================================================================
# 4. Station 2 → Station 3 Integration (handoff smoke test)
# ===========================================================================

def test_station2_output_flows_into_station3():
    """
    Verify that the exact LockedPICO shape Station 2 produces
    (as shown in the project example output) works without errors.
    """
    # This is the literal output from Station 2's demo
    pico = LockedPICO(
        raw_claim="Is turmeric good for inflammation?",
        food="turmeric",
        form="supplement",
        dose=None,
        frequency=None,
        population="healthy_adults",
        component=None,
        outcome="inflammation",
        ambiguous_slots=["form", "dose", "frequency", "population", "component"],
        locked=True,
        conversation=[
            ["Are you asking about turmeric as food or as a supplement?",
             "As a curcumin supplement (standardized extract pills)"],
            ["Who is the question about?", "Healthy adults"],
        ],
        fallbacks_used=[],
    )
    client = stub_pubmed()
    agent = RetrievalAgent(pubmed_client=client, log_file="/tmp/test_handoff.jsonl")
    result = agent.retrieve(pico)
    assert isinstance(result, RetrievalResult)
    assert result.query_used != ""
    # Query should contain turmeric synonyms (curcumin is in FOOD_SYNONYMS for turmeric)
    assert any(
        term in result.query_used.lower()
        for term in ["turmeric", "curcumin", "curcuma longa"]
    )