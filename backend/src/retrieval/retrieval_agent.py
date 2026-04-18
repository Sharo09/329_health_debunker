"""Station 3: Retrieval Agent.

Takes a ``LockedPICO`` from Station 2 and returns a ``RetrievalResult``
containing the retrieved papers, the final query used, and a full audit log.

Algorithm (agentic loop)
------------------------
1.  Validate the LockedPICO has the minimum required slots (food + outcome).
2.  Try building and executing a PubMed query at the most specific
    relaxation level (FULL).
3.  If the result count is below MIN_PAPER_THRESHOLD, relax the query
    by one level and retry.
4.  Repeat until results are sufficient or all relaxation levels are
    exhausted.
5.  Fetch full records (title, abstract, metadata) for the selected PMIDs.
6.  Apply post-fetch filters (retraction flag, language, empty records).
7.  Return a RetrievalResult. Scoring is Station 4's responsibility.

Edge cases handled
------------------
- food or outcome missing         → raises UnretrievableClaimError
- PubMed returns 0 hits           → log and relax; report below_threshold
- All levels return 0 hits        → return empty result with below_threshold=True
- Retracted papers                → kept but is_retracted=True; Station 4 decides
- Non-English papers              → filtered by default; keep_non_english flag overrides
- Papers with no title+abstract   → discarded (indexing errors)
- More PMIDs than soft cap        → cap fetch; relevance scorer will trim further
- Network errors / timeouts       → tenacity retry inside PubMedClient
- PubMed phrase parse warnings    → logged; query continues
- Underscored population values   → normalised in QueryBuilder
- Compound food claims (and/or)   → Station 2 already resolves these; handled upstream
- form stored as long display text → FORM_TERMS lookup covers Station 2's exact strings
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from backend.src.retrieval.errors import UnretrievableClaimError
from backend.src.retrieval.pubmed_client import PubMedClient
from backend.src.retrieval.query_builder import QueryBuilder, RelaxationLevel
from backend.src.retrieval.schemas import Paper, RetrievalResult
from backend.src.schemas import LockedPICO   # shared schema from Station 2

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_PAPER_THRESHOLD = 10    # warn if final paper count falls below this
SOFT_CAP = 40               # pass at most this many papers to Station 4
HARD_FETCH_LIMIT = 80       # never ask PubMed for more than this many PMIDs
DEFAULT_LOG_FILE = "logs/retrieval.jsonl"


# ===========================================================================
# Retrieval Agent
# ===========================================================================

class RetrievalAgent:
    """
    Agentic PubMed retrieval loop for Station 3.

    Parameters
    ----------
    pubmed_client     : PubMedClient instance (injectable for testing).
    keep_non_english  : If True, non-English papers are kept in results.
    min_threshold     : Warn if final paper count is below this.
    soft_cap          : Cap the final paper list at this size.
    log_file          : Path to the JSONL audit log.
    """

    def __init__(
        self,
        pubmed_client: Optional[PubMedClient] = None,
        keep_non_english: bool = False,
        min_threshold: int = MIN_PAPER_THRESHOLD,
        soft_cap: int = SOFT_CAP,
        log_file: Optional[str] = None,
    ):
        self.pubmed = pubmed_client or PubMedClient()
        self.keep_non_english = keep_non_english
        self.min_threshold = min_threshold
        self.soft_cap = soft_cap
        self.log_file = log_file or DEFAULT_LOG_FILE
        self._query_builder = QueryBuilder()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def retrieve(self, pico: LockedPICO) -> RetrievalResult:
        """
        Main entry point.  Accepts a ``LockedPICO`` from Station 2 and
        returns a ``RetrievalResult`` for Station 4.

        Raises
        ------
        UnretrievableClaimError  if both food and outcome are absent.
        """
        self._validate(pico)

        audit_log: list[dict] = []
        final_pmids: list[str] = []
        final_count: int = 0
        final_query: str = ""
        final_level: RelaxationLevel = RelaxationLevel.FULL

        # ---- Agentic query loop ----
        for level in RelaxationLevel:
            query, pmids, count, log_entry = self._try_level(pico, level)
            audit_log.append(log_entry)

            if count == 0:
                logger.info("[%s] Zero hits; relaxing query.", level.name)
                continue

            final_pmids = pmids
            final_count = count
            final_query = query
            final_level = level

            if len(final_pmids) >= self.min_threshold:
                logger.info(
                    "[%s] %d PMIDs ≥ threshold %d. Stopping.",
                    level.name, len(final_pmids), self.min_threshold,
                )
                break

            logger.info(
                "[%s] %d PMIDs < threshold %d. Relaxing further.",
                level.name, len(final_pmids), self.min_threshold,
            )

        # ---- Cap before fetch ----
        if len(final_pmids) > HARD_FETCH_LIMIT:
            logger.info(
                "Capping fetch from %d to %d PMIDs.", len(final_pmids), HARD_FETCH_LIMIT
            )
            audit_log.append({
                "note": f"PMID list capped {len(final_pmids)} → {HARD_FETCH_LIMIT}."
            })
            final_pmids = final_pmids[:HARD_FETCH_LIMIT]

        # ---- Fetch full records ----
        papers: list[Paper] = []
        if final_pmids:
            logger.info("Fetching %d full records from PubMed.", len(final_pmids))
            papers = self.pubmed.fetch(final_pmids)
            logger.info("Parsed %d papers.", len(papers))
            papers = self._filter_papers(papers)
        else:
            logger.warning("No PMIDs to fetch for claim: %r", pico.raw_claim)

        # Cap at soft_cap (Station 4's relevance scorer will re-sort and trim further)
        if len(papers) > self.soft_cap:
            papers = papers[:self.soft_cap]

        below_threshold = len(papers) < self.min_threshold
        if below_threshold:
            logger.warning(
                "Final count %d < threshold %d for claim: %r",
                len(papers), self.min_threshold, pico.raw_claim,
            )

        result = RetrievalResult(
            papers=papers,
            query_used=final_query,
            relaxation_level=int(final_level),
            total_pubmed_hits=final_count,
            below_threshold=below_threshold,
            audit_log=audit_log,
        )

        self._log(pico, result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate(self, pico: LockedPICO) -> None:
        if not pico.food and not pico.outcome:
            raise UnretrievableClaimError(
                "LockedPICO is missing both 'food' and 'outcome'. "
                "Cannot build any PubMed query."
            )
        # Warn (not raise) on missing food OR outcome individually —
        # the QueryBuilder handles missing slots gracefully.
        if not pico.food:
            logger.warning("LockedPICO missing 'food'; query will be outcome-only.")
        if not pico.outcome:
            logger.warning("LockedPICO missing 'outcome'; query will be food-only.")

    def _try_level(
        self, pico: LockedPICO, level: RelaxationLevel
    ) -> tuple[str, list[str], int, dict]:
        """
        Attempt one query at the given relaxation level.

        Returns (query_string, pmids, count, audit_entry).
        On any error, returns ("", [], 0, audit_entry_with_error).
        """
        try:
            query = self._query_builder.build(pico, level)
        except ValueError as e:
            logger.error("[%s] Query build failed: %s", level.name, e)
            return "", [], 0, {
                "level": level.name,
                "query": None,
                "error": str(e),
                "timestamp": _now(),
            }

        logger.info("[%s] Query: %s", level.name, query)

        try:
            pmids, count = self.pubmed.search(query, max_results=HARD_FETCH_LIMIT)
        except Exception as e:
            logger.warning("[%s] PubMed search error: %s", level.name, e)
            return query, [], 0, {
                "level": level.name,
                "query": query,
                "total_hits": 0,
                "error": str(e),
                "timestamp": _now(),
            }

        return query, pmids, count, {
            "level": level.name,
            "query": query,
            "total_hits": count,
            "pmids_returned": len(pmids),
            "timestamp": _now(),
        }

    def _filter_papers(self, papers: list[Paper]) -> list[Paper]:
        """
        Post-fetch filters applied before passing to Station 4.

        Rules
        -----
        1.  Papers with neither title nor abstract are discarded — they are
            almost certainly indexing stubs with no retrievable content.
        2.  Non-English papers are filtered unless keep_non_english is True.
        3.  Retracted papers are KEPT but flagged (is_retracted=True).
            Station 4 must decide whether to exclude or down-weight them.
        """
        kept: list[Paper] = []
        for p in papers:
            if not p.title and not p.abstract:
                logger.debug("Discarding PMID %s: no title and no abstract.", p.pmid)
                continue
            if not self.keep_non_english and p.language not in ("eng", "en", ""):
                logger.debug(
                    "Discarding PMID %s: language=%r.", p.pmid, p.language
                )
                continue
            kept.append(p)
        return kept

    def _log(self, pico: LockedPICO, result: RetrievalResult) -> None:
        """Append a JSONL audit record to the log file."""
        record = {
            "timestamp": _now(),
            "raw_claim": pico.raw_claim,
            "locked_pico": {
                "food": pico.food,
                "form": pico.form,
                "dose": pico.dose,
                "frequency": pico.frequency,
                "population": pico.population,
                "component": pico.component,
                "outcome": pico.outcome,
            },
            "query_used": result.query_used,
            "relaxation_level": result.relaxation_level,
            "total_pubmed_hits": result.total_pubmed_hits,
            "papers_retrieved": len(result.papers),
            "below_threshold": result.below_threshold,
            "audit_log": result.audit_log,
        }
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")


# ---------------------------------------------------------------------------
# Convenience entry point (called by Station 4 and integration tests)
# ---------------------------------------------------------------------------

def retrieve(pico: LockedPICO) -> RetrievalResult:
    """
    Single-function entry point.  Creates a default RetrievalAgent and
    calls retrieve(pico).

    Usage
    -----
    from src.retrieval.retrieval_agent import retrieve
    result = retrieve(locked_pico)
    """
    return RetrievalAgent().retrieve(pico)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# OPTIONAL: STATION 4 PREVIEW — Evidence Extraction & Relevance Scoring
# ===========================================================================
# Everything below this line belongs to Station 4 (Synthesis).
# It is included here as a prototype so the team can see how these two steps
# look in code and how they integrate with Station 3's output.
#
# Station 4 should import these classes from its own module, not from here.
# When Station 4 is ready, move these to src/synthesis/ and delete them here.
# ===========================================================================

import os as _os
import json as _json

try:
    import requests as _requests
    _requests_available = True
except ImportError:
    _requests_available = False


# ---------------------------------------------------------------------------
# OPTIONAL: Evidence Sentence Extractor
# ---------------------------------------------------------------------------

class EvidenceExtractor:
    """
    [STATION 4 PREVIEW — OPTIONAL]

    Extracts the single most relevant sentence (or clause) from a paper's
    abstract that directly speaks to the user's claim.

    This is the "claim/conclusion retrieved from the paper" that the professor
    described when saying relevance scoring should be done on the extracted
    claim, not the full abstract.

    How it works
    ------------
    A lightweight LLM prompt asks Gemini to:
      1. Find the sentence in the abstract that most directly addresses
         the user's PICO (food + outcome).
      2. Return that sentence verbatim, or a short paraphrase if no single
         sentence is suitable.
      3. Also return a one-word stance label: "supports", "contradicts",
         or "unclear" (used by Station 4's deterministic verdict rules).

    Falls back to the last sentence of the abstract when no LLM is available,
    since abstracts typically end with the conclusion.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or _os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning(
                "[EvidenceExtractor] No GEMINI_API_KEY; using last-sentence fallback."
            )

    def extract(self, paper: Paper, pico: LockedPICO) -> dict:
        """
        Returns a dict with keys:
            evidence_sentence : str   — the extracted claim/conclusion
            stance            : str   — "supports" | "contradicts" | "unclear"
        """
        if not paper.abstract:
            return {
                "evidence_sentence": paper.title,
                "stance": "unclear",
            }

        if self.api_key and _requests_available:
            try:
                return self._llm_extract(paper, pico)
            except Exception as e:
                logger.warning(
                    "[EvidenceExtractor] LLM failed for PMID %s: %s. Using fallback.",
                    paper.pmid, e,
                )

        return self._fallback_extract(paper)

    def _llm_extract(self, paper: Paper, pico: LockedPICO) -> dict:
        snippet = paper.abstract[:1000]
        prompt = f"""You are a scientific evidence extractor for a food and nutrition fact-checking system.

USER'S CLAIM: "{pico.raw_claim}"
FOOD: {pico.food}
OUTCOME: {pico.outcome}

PAPER ABSTRACT:
{snippet}

TASK:
1. Find the single sentence (or short clause) from the abstract that most directly addresses whether {pico.food} affects {pico.outcome}.
2. Classify the stance of that sentence as one of: "supports", "contradicts", or "unclear".

IMPORTANT: Do NOT lower the relevance of a sentence just because it contradicts the user's claim. Contradiction is still relevant evidence.

Respond ONLY with valid JSON (no markdown, no extra text):
{{"evidence_sentence": "<sentence or short paraphrase>", "stance": "<supports|contradicts|unclear>"}}"""

        resp = _requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={self.api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 150},
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = _json.loads(clean)
        return {
            "evidence_sentence": str(data.get("evidence_sentence", "")),
            "stance": str(data.get("stance", "unclear")).lower(),
        }

    def _fallback_extract(self, paper: Paper) -> dict:
        """Return the last non-empty sentence of the abstract."""
        sentences = [s.strip() for s in paper.abstract.split(".") if s.strip()]
        last = sentences[-1] if sentences else paper.abstract[:200]
        return {"evidence_sentence": last + ".", "stance": "unclear"}


# ---------------------------------------------------------------------------
# OPTIONAL: Relevance Scorer
# ---------------------------------------------------------------------------

class RelevanceScorer:
    """
    [STATION 4 PREVIEW — OPTIONAL]

    Scores each paper's relevance to the user's claim using an LLM.

    Scoring contract (per professor's instructions)
    ------------------------------------------------
    - Score is based SOLELY on how closely the paper's conclusion addresses
      the user's claim (food + outcome + population).
    - A paper that CONTRADICTS the claim scores just as high as one that
      SUPPORTS it, provided it studies the same food-outcome pair.
    - Score range: 0.0 (unrelated) → 1.0 (directly on-point).

    The scorer calls the LLM once per paper. Station 4 should batch these
    calls or run them in parallel (asyncio / ThreadPoolExecutor) to keep
    latency manageable.
    """

    DISCARD_THRESHOLD = 0.10   # papers scoring below this are dropped

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or _os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning(
                "[RelevanceScorer] No GEMINI_API_KEY; using keyword-overlap heuristic."
            )

    def score(self, paper: Paper, pico: LockedPICO) -> tuple[float, str]:
        """
        Score a single paper.

        Returns
        -------
        (score, reasoning)  — score in [0.0, 1.0], one-sentence reasoning string.
        """
        if self.api_key and _requests_available:
            try:
                return self._llm_score(paper, pico)
            except Exception as e:
                logger.warning(
                    "[RelevanceScorer] LLM failed for PMID %s: %s. Using heuristic.",
                    paper.pmid, e,
                )
        return self._heuristic_score(paper, pico)

    def score_all(self, papers: list[Paper], pico: LockedPICO) -> list[Paper]:
        """
        Score every paper, attach scores, discard clearly irrelevant papers,
        and return the list sorted by relevance descending.

        This mutates the relevance_score and relevance_reasoning fields on
        each Paper object in-place.
        """
        scored: list[Paper] = []
        for paper in papers:
            s, r = self.score(paper, pico)
            paper.relevance_score = max(0.0, min(1.0, s))
            paper.relevance_reasoning = r
            if paper.relevance_score >= self.DISCARD_THRESHOLD:
                scored.append(paper)
            else:
                logger.debug(
                    "Discarding PMID %s (score=%.2f): %s", paper.pmid, s, r
                )
        scored.sort(key=lambda p: p.relevance_score, reverse=True)
        return scored

    def _llm_score(self, paper: Paper, pico: LockedPICO) -> tuple[float, str]:
        snippet = paper.abstract[:800] if paper.abstract else "[No abstract]"
        prompt = f"""You are a scientific evidence relevance assessor for a nutrition fact-checking system.

USER'S CLAIM: "{pico.raw_claim}"
PICO:
  Food/ingredient : {pico.food or "not specified"}
  Health outcome  : {pico.outcome or "not specified"}
  Population      : {pico.population or "not specified"}
  Form            : {pico.form or "not specified"}
  Component       : {pico.component or "not specified"}

PAPER:
  Title    : {paper.title}
  Abstract : {snippet}

SCORE this paper's relevance to the user's claim from 0.0 to 1.0.

CRITICAL RULE: A paper that CONTRADICTS the claim is just as relevant as one that
SUPPORTS it, as long as it directly studies the same food-outcome pair.
Only reduce the score if the paper studies something genuinely different.

Guide:
  1.0 — Same food, same outcome, same (or similar) population.
  0.7 — Same food and outcome; population or form differs somewhat.
  0.4 — Related food or related outcome, not directly on-point.
  0.1 — Tangentially related.
  0.0 — Completely unrelated.

Respond ONLY with valid JSON (no markdown):
{{"score": <float>, "reasoning": "<one sentence>"}}"""

        resp = _requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={self.api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 120},
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        data = _json.loads(clean)
        score = float(data["score"])
        return score, data.get("reasoning", "")

    def _heuristic_score(self, paper: Paper, pico: LockedPICO) -> tuple[float, str]:
        """
        Keyword-overlap fallback. Counts how many PICO terms appear in the
        title + abstract. Not a substitute for LLM scoring — last resort only.
        """
        haystack = f"{paper.title} {paper.abstract}".lower()
        pico_terms = [
            t.strip().lower()
            for t in [pico.food, pico.component, pico.outcome]
            if t
        ]
        if not pico_terms:
            return 0.0, "Heuristic: no PICO terms available."
        hits = sum(1 for t in pico_terms if t in haystack)
        score = round(hits / len(pico_terms), 2)
        return score, f"Heuristic: {hits}/{len(pico_terms)} PICO terms matched."