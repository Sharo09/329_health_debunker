"""
backend/main.py
===============
FastAPI backend for the Health Myth Debunker.

This file connects your existing Station 1, 2, and 3 code to a web API.
Station 4 (synthesis) is not yet built, so the /api/finalize endpoint
returns the retrieved papers directly for now. You can add synthesis later.

Two API endpoints:
    POST /api/extract   — runs Station 1 + builds Station 2 questions
    POST /api/finalize  — runs Station 3 retrieval and returns papers

Everything else (/) is served from the built React frontend.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
load_dotenv()   # loads your .env file so GEMINI_API_KEY is available

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Make sure Python can find the backend package when running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load local environment variables from backend/.env in development
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# --- Station 1 imports ---
# Sharon's original imports pointed at a ``backend/src/*`` copy of the
# backend. The canonical backend now lives at the repo root under
# ``src/`` (rebuilt per docs/retrieval_spec.md). We import from there
# so the FastAPI wrapper shares code with demo.py and the test suite.
from src.extraction.extractor import ClaimExtractor
from src.extraction.llm_client import LLMClient
from src.extraction.schemas import PartialPICO, SlotExtraction

# --- Station 2 imports ---
from src.elicitation.priority_table import get_priority
from src.elicitation.question_templates import get_question

# --- Station 3 imports ---
# ``RetrievalAgent`` re-exports the rebuilt agent (retrieval_agent_new).
# The legacy one is available as ``LegacyRetrievalAgent`` if needed.
from src.retrieval import RetrievalAgent

# --- Station 4 imports ---
from src.synthesis import (
    Paper as ScorePaper,
    ScoreRequest,
    UserProfile,
    analyze_claim,
)

# --- Shared schema ---
from src.schemas import LockedPICO

# Station 2 population token → Station 4 DemographicGroup literal.
_POPULATION_TO_DEMOGRAPHIC: dict[str, str] = {
    "healthy_adults": "adults",
    "healthy_replete": "adults",
    "children": "children",
    "infants": "infants",
    "adolescents": "adolescents",
    "elderly": "older_adults",
    "pregnant": "adults",
    "obese": "adults",
    "diabetic": "adults",
    "hypercholesterolemia": "adults",
    "deficient": "adults",
    "inflammatory_patients": "adults",
    "cardiovascular_patients": "adults",
    "liver_patients": "adults",
    "lactose_intolerant": "general",
    "condition": "general",
}


def _locked_to_user_profile(locked, age: Optional[int]) -> UserProfile:
    demographic = _POPULATION_TO_DEMOGRAPHIC.get(
        (locked.population or "").lower(), "general"
    )
    return UserProfile(age=age, demographic_group=demographic)


def _retrieved_to_score_paper(p) -> ScorePaper:
    """Adapt Station 3's RetrievedPaper to Station 4's Paper schema."""
    abstract = p.abstract or p.title
    sentences = [s.strip() for s in abstract.split(".") if s.strip()]
    if len(sentences) >= 2:
        claim_text = sentences[-2] + ". " + sentences[-1] + "."
    elif sentences:
        claim_text = sentences[-1] + "."
    else:
        claim_text = abstract[:300]
    return ScorePaper(
        paper_id=p.pmid,
        title=p.title,
        extracted_claim=claim_text,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{p.pmid}/",
        population_studied=None,
        nutritional_components=[],
    )


def _mock_gemini_provider(
    messages: list[dict],
    response_schema: type[BaseModel],
    model: str,
    temperature: float,
) -> str:
    """Mock provider for testing when API quota is exceeded.

    Returns a JSON string that matches the expected PartialPICO schema.
    """
    # Extract the claim from the messages
    claim_text = ""
    for message in messages:
        if message.get("role") == "user":
            claim_text = message.get("content", "")
            break

    claim_lower = claim_text.lower()

    # Create mock data based on claim content
    if "turmeric" in claim_lower:
        food = "turmeric"
        outcome = "inflammation"
        component = "curcumin"
    elif "coffee" in claim_lower:
        food = "coffee"
        outcome = "headaches"
        component = None
    elif "vitamin" in claim_lower:
        food = "vitamin D"
        outcome = "bone health"
        component = None
    else:
        food = "test food"
        outcome = "test outcome"
        component = None

    # Return JSON that matches PartialPICO schema
    mock_json = {
        "raw_claim": claim_text,
        "food": {"value": food, "confidence": "explicit", "source_span": food},
        "form": {"value": "supplement", "confidence": "implied"},
        "dose": {"value": None, "confidence": "absent"},
        "frequency": {"value": None, "confidence": "absent"},
        "population": {"value": "adults", "confidence": "implied"},
        "component": {"value": component, "confidence": "implied"} if component else {"value": None, "confidence": "absent"},
        "outcome": {"value": outcome, "confidence": "explicit", "source_span": outcome},
        "ambiguous_slots": ["dose", "frequency"],
        "is_food_claim": True,
        "scope_rejection_reason": None,
        "notes": None
    }

    import json
    return json.dumps(mock_json)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Health Myth Debunker API")

# CORS lets the React frontend (running on localhost:5173 during dev) talk
# to this backend (running on localhost:8000).
# In production they're on the same domain so CORS won't matter, but it's
# harmless to leave it in.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Serve the built React frontend
# ---------------------------------------------------------------------------
# In production (Docker on Cloud Run), the built React files are copied into
# backend/static/. When running locally for development, this folder won't
# exist and that's fine — you run the React dev server separately.

STATIC_DIR = Path(__file__).resolve().parent / "static"

if STATIC_DIR.exists():
    # Serve JS/CSS/image assets at /assets/...
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def serve_index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Send all non-API routes to React's index.html (client-side routing)."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found.")
        return FileResponse(STATIC_DIR / "index.html")

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ExtractRequest(BaseModel):
    claim: str


class QuestionOut(BaseModel):
    slot: str
    text: str
    option_values: List[str] = Field(default_factory=list)
    option_labels: List[str] = Field(default_factory=list)


class ExtractResponse(BaseModel):
    is_food_claim: bool
    scope_rejection_reason: Optional[str] = None
    partial_pico: Dict[str, Any]    # flat string fields — safe to send to frontend
    questions: List[QuestionOut]


class FinalizeRequest(BaseModel):
    partial_pico: Dict[str, Any]
    answers: Dict[str, str] = Field(default_factory=dict)
    age: Optional[int] = None


class PaperOut(BaseModel):
    pmid: str
    title: str
    abstract: str
    journal: str
    pub_year: Optional[int]
    pub_types: List[str]
    pubmed_url: str
    is_retracted: bool


class CitedPaperOut(BaseModel):
    """One paper cited in the verdict, grouped by stance."""
    paper_id: str
    title: str
    url: Optional[str] = None
    stance: str                    # supports | contradicts | neutral | unclear
    relevance_score: float
    applies_to: List[str] = Field(default_factory=list)
    demographic_match: bool = False
    one_line_summary: str = ""


class VerdictOut(BaseModel):
    """Station 4 synthesis output, shaped for the frontend."""
    verdict: str                   # supported | contradicted | insufficient_evidence
    confidence_percent: float
    verdict_reasoning: str
    demographic_caveat: Optional[str] = None
    supporting_papers: List[CitedPaperOut] = Field(default_factory=list)
    contradicting_papers: List[CitedPaperOut] = Field(default_factory=list)
    neutral_papers: List[CitedPaperOut] = Field(default_factory=list)


class FinalizeResponse(BaseModel):
    below_threshold: bool
    total_pubmed_hits: int
    query_used: str
    relaxation_level: int
    papers: List[PaperOut]
    warning: Optional[str] = None
    # Station 4 verdict. Always None on /api/finalize — call /api/synthesize
    # to get the verdict in a separate request (so the UI can show retrieved
    # papers immediately while the slow verdict step runs).
    verdict: Optional[VerdictOut] = None
    # Echo the locked PICO so the UI can display it without rebuilding.
    raw_claim: str = ""
    locked_food: Optional[str] = None
    locked_outcome: Optional[str] = None
    locked_population: Optional[str] = None
    locked_form: Optional[str] = None
    locked_component: Optional[str] = None


class SynthesizeRequest(BaseModel):
    """Synthesize a verdict from previously-retrieved papers.

    Carries the same partial_pico + answers + age as /api/finalize so
    the backend can rebuild the LockedPICO and derive the user profile
    consistently. ``papers`` are the ones returned from /api/finalize.
    """
    partial_pico: Dict[str, Any]
    answers: Dict[str, str] = Field(default_factory=dict)
    age: Optional[int] = None
    papers: List[PaperOut] = Field(default_factory=list)


class SynthesizeResponse(BaseModel):
    verdict: VerdictOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_questions(flat_pico: dict, food: str) -> List[QuestionOut]:
    """
    Replicate what Station 2's ElicitationAgent does, but return the questions
    as JSON instead of printing them to the terminal.

    We use the same get_priority() and get_question() functions that
    Station 2 already uses internally, so the questions are identical.
    """
    ambiguous = flat_pico.get("ambiguous_slots", [])
    questions: List[QuestionOut] = []

    for slot in get_priority(food):
        if len(questions) >= 3:
            break
        if slot not in ambiguous:
            continue
        if flat_pico.get(slot) is not None:
            continue

        tmpl = dict(get_question(slot, food))
        # Station 2 question templates store options as parallel lists:
        # tmpl["option_values"] and tmpl["option_labels"]
        # (Some templates may store them differently — we handle both shapes.)
        values = tmpl.get("option_values", [])
        labels = tmpl.get("option_labels", values)   # fall back to values if no labels

        questions.append(QuestionOut(
            slot=slot,
            text=tmpl.get("text", ""),
            option_values=list(values),
            option_labels=list(labels),
        ))

    return questions


def _build_locked_pico(partial_pico: dict, answers: dict, age: Optional[int]) -> LockedPICO:
    """
    Merge the flat partial PICO from Station 1 with the user's answers
    to build a LockedPICO ready for Station 3.
    """
    data = dict(partial_pico)

    # Apply answers from the frontend dropdowns
    for slot, value in answers.items():
        if value and str(value).strip():
            data[slot] = str(value).strip()

    # If the user provided their age, convert it to a population group
    # and fill it in only if population wasn't already answered
    if age is not None and not data.get("population"):
        data["population"] = _age_to_population(age)

    # LockedPICO requires these fields even if None
    data.setdefault("food", None)
    data.setdefault("form", None)
    data.setdefault("dose", None)
    data.setdefault("frequency", None)
    data.setdefault("population", None)
    data.setdefault("component", None)
    data.setdefault("outcome", None)
    data.setdefault("ambiguous_slots", [])

    return LockedPICO(
        **data,
        locked=True,
        conversation=[],
        fallbacks_used=[],
    )


def _age_to_population(age: int) -> str:
    if age < 13:
        return "children"
    if age < 18:
        return "adolescents"
    if age < 65:
        return "healthy_adults"
    return "older_adults"


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/extract", response_model=ExtractResponse)
def extract_claim(req: ExtractRequest):
    """
    Station 1: extract PICO slots from the raw claim.
    Then build the clarifying questions Station 2 would ask.

    Called by the frontend when the user clicks "Start Analysis".
    """
    if not req.claim or not req.claim.strip():
        raise HTTPException(status_code=422, detail="Claim cannot be empty.")

    # Initialise Station 1 using the Gemini API key from environment
    try:
        # Try with real API first
        llm = LLMClient()  # reads GEMINI_API_KEY from environment itself
        extractor = ClaimExtractor(llm_client=llm)
        partial = extractor.extract(req.claim)
    except Exception as e:
        error_msg = str(e)
        if "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
            # API quota exceeded - fall back to mock provider
            print("API quota exceeded, using mock provider for testing")
            mock_llm = LLMClient(provider=_mock_gemini_provider)
            mock_extractor = ClaimExtractor(llm_client=mock_llm)
            partial = mock_extractor.extract(req.claim)
        else:
            # Re-raise other errors
            raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    if not partial.is_food_claim:
        return ExtractResponse(
            is_food_claim=False,
            scope_rejection_reason=partial.scope_rejection_reason,
            partial_pico={},
            questions=[],
        )

    # Convert PartialPICO → flat dict for JSON transport
    flat = partial.to_flat()
    flat_dict = flat.model_dump()

    food = flat_dict.get("food") or ""
    questions = _build_questions(flat_dict, food)

    return ExtractResponse(
        is_food_claim=True,
        partial_pico=flat_dict,
        questions=questions,
    )


@app.post("/api/finalize", response_model=FinalizeResponse)
def finalize_claim(req: FinalizeRequest):
    """
    Station 3: retrieve papers from PubMed using the locked PICO.

    Called by the frontend when the user answers the clarifying questions
    and clicks "Run Analysis".

    NOTE: Station 4 (synthesis/verdict) is not yet implemented. This endpoint
    returns the raw retrieved papers. When Station 4 is ready, add it here.
    """
    try:
        locked = _build_locked_pico(req.partial_pico, req.answers, req.age)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not build locked PICO: {e}")

    if not locked.food and not locked.outcome:
        raise HTTPException(
            status_code=422,
            detail="Both food and outcome are missing. Cannot retrieve evidence.",
        )

    try:
        agent = RetrievalAgent(log_file="logs/retrieval.jsonl")
        result = agent.retrieve(locked)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {e}")

    # RetrievalResultV2 uses different fields than Sharon's legacy API.
    # Translate them into the frontend's existing ``FinalizeResponse`` shape
    # so her React code works unchanged.
    papers_out = [
        PaperOut(
            pmid=p.pmid,
            title=p.title,
            abstract=p.abstract,
            journal=p.journal,
            pub_year=p.year,                # renamed field on RetrievedPaper
            pub_types=p.pub_types,
            pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{p.pmid}/",
            is_retracted=p.is_retracted,
        )
        for p in result.papers
    ]

    total_pubmed_hits = (
        max((q.hit_count for q in result.queries_executed), default=0)
    )
    last_query = (
        result.queries_executed[-1].query_string if result.queries_executed else ""
    )
    # The new agent doesn't use the numeric relaxation ladder; surface the
    # number of queries it took as a rough proxy for "how hard we had to look".
    relaxation_proxy = max(0, len(result.queries_executed) - 1)
    below_threshold = len(papers_out) < 10

    warning = None
    if below_threshold:
        warning = (
            f"Only {len(papers_out)} paper(s) were found for this claim. "
            "Results may be limited. Try broadening your query."
        )

    # /api/finalize is now retrieval-only. The frontend calls /api/synthesize
    # in a second request so it can show retrieved papers immediately while
    # the (slow) verdict step runs in the background.
    return FinalizeResponse(
        below_threshold=below_threshold,
        total_pubmed_hits=total_pubmed_hits,
        query_used=last_query,
        relaxation_level=relaxation_proxy,
        papers=papers_out,
        warning=warning,
        verdict=None,
        raw_claim=locked.raw_claim,
        locked_food=locked.food,
        locked_outcome=locked.outcome,
        locked_population=locked.population,
        locked_form=locked.form,
        locked_component=locked.component,
    )


def _to_cited_paper_out(cp) -> CitedPaperOut:
    """Convert a Station 4 CitedPaper to the API response shape."""
    return CitedPaperOut(
        paper_id=cp.paper_id,
        title=cp.title,
        url=cp.url,
        stance=cp.stance,
        relevance_score=cp.relevance_score,
        applies_to=[str(x) for x in (cp.applies_to or [])],
        demographic_match=bool(cp.demographic_match),
        one_line_summary=cp.one_line_summary,
    )


@app.post("/api/synthesize", response_model=SynthesizeResponse)
def synthesize_claim(req: SynthesizeRequest):
    """Station 4: synthesize a verdict from previously-retrieved papers.

    The frontend hits this AFTER /api/finalize so retrieved papers can
    be shown immediately while the verdict cooks in the background.
    """
    if not req.papers:
        raise HTTPException(
            status_code=422, detail="No papers provided to synthesize."
        )

    try:
        locked = _build_locked_pico(req.partial_pico, req.answers, req.age)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not rebuild locked PICO: {e}")

    # PaperOut → ScorePaper for Station 4 input.
    score_papers_in = []
    for p in req.papers[:40]:
        abstract = p.abstract or p.title
        sentences = [s.strip() for s in abstract.split(".") if s.strip()]
        if len(sentences) >= 2:
            claim_text = sentences[-2] + ". " + sentences[-1] + "."
        elif sentences:
            claim_text = sentences[-1] + "."
        else:
            claim_text = abstract[:300]
        score_papers_in.append(
            ScorePaper(
                paper_id=p.pmid,
                title=p.title,
                extracted_claim=claim_text,
                url=p.pubmed_url,
                population_studied=None,
                nutritional_components=[],
            )
        )

    try:
        analysis = analyze_claim(
            ScoreRequest(
                user_claim=locked.raw_claim,
                user_profile=_locked_to_user_profile(locked, req.age),
                papers=score_papers_in,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {e}")

    v = analysis.verdict
    return SynthesizeResponse(
        verdict=VerdictOut(
            verdict=v.verdict,
            confidence_percent=v.confidence_percent,
            verdict_reasoning=v.verdict_reasoning,
            demographic_caveat=v.demographic_caveat,
            supporting_papers=[_to_cited_paper_out(cp) for cp in v.supporting_papers],
            contradicting_papers=[_to_cited_paper_out(cp) for cp in v.contradicting_papers],
            neutral_papers=[_to_cited_paper_out(cp) for cp in v.neutral_papers],
        )
    )


# ---------------------------------------------------------------------------
# Health check (useful for Cloud Run to verify the container started)
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health_check():
    return {"status": "ok"}