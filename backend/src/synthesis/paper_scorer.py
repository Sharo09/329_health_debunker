"""Station 4 — Synthesis.

Scores retrieved papers for topic-relevance and emits a final verdict.
Uses Google Gemini (via ``google-genai``) for structured LLM output.

Two-step pipeline
-----------------
Step 1 — score_papers()       : scores each paper for topical relevance
                                 (not agreement) and flags demographic fit.
Step 2 — generate_verdict()   : synthesises the scored papers into a single
                                 verdict ("supported" | "contradicted" |
                                 "insufficient_evidence") with confidence %.

FastAPI endpoints are retained so the module can still be served as a
web backend if desired.
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException
from google import genai
from google.genai import types

from backend.src.synthesis.schemas import (
    AnalysisResponse,
    Paper,
    PaperScoreResult,
    ScoreList,
    ScoreRequest,
    ScoreResponse,
    UserProfile,
    VerdictResult,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gemini-2.5-flash"

# Cached Client: creating a new genai.Client per call can leave earlier
# instances (e.g., Station 1's extraction client) in a closed state,
# surfacing as ``RuntimeError: client has been closed``. Keeping one
# long-lived client sidesteps the shared-state quirk.
_CACHED_CLIENT: genai.Client | None = None


def _client() -> genai.Client:
    """Return the module-level Gemini client, creating it on first use."""
    global _CACHED_CLIENT
    if _CACHED_CLIENT is None:
        if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
            raise RuntimeError(
                "Neither GOOGLE_API_KEY nor GEMINI_API_KEY is set. "
                "Set one before calling Station 4 synthesis."
            )
        _CACHED_CLIENT = genai.Client()
    return _CACHED_CLIENT


# ---------------------------------------------------------------------------
# Step 1 — Scoring
# ---------------------------------------------------------------------------

_SCORING_SYSTEM_PROMPT = """\
You are a biomedical research analyst scoring research papers for topical relevance \
to a user's health claim.

CRITICAL SCORING RULE:
  Relevance is about TOPIC SIMILARITY, not agreement.
  A paper that CONTRADICTS the user's claim is equally as relevant as one that SUPPORTS it,
  if it addresses the same subject, substance, mechanism, or health outcome.
  Never lower a score because a paper disagrees with the user's claim.

For each paper you will be given:
  - The user's health claim
  - The user's demographic profile
  - The paper's extracted conclusion / claim
  - The study population (if available)
  - Relevant nutritional/chemical components (if available)

Relevance score guidance:
  0.8–1.0 : Paper directly addresses the same substance/mechanism/outcome as the claim
  0.5–0.79: Paper is on a closely related topic (e.g. same substance, different outcome)
  0.2–0.49: Paper is tangentially related (e.g. related compound, same disease different pathway)
  0.0–0.19: Paper is largely unrelated to the claim's topic

demographic_match = true if the paper's study population includes or broadly overlaps with the user's age group.

Return a JSON object matching the provided schema. The `scores` field must contain
one entry per paper, in the same order as the input.
"""


def _build_scoring_message(request: ScoreRequest) -> str:
    lines: list[str] = [
        f"USER CLAIM: {request.user_claim}",
        "",
        "USER PROFILE:",
        f"  Age: {request.user_profile.age if request.user_profile.age is not None else 'unknown'}",
        f"  Demographic group: {request.user_profile.demographic_group}",
        "",
        "PAPERS TO SCORE:",
    ]
    for i, paper in enumerate(request.papers, 1):
        lines.append(f"\n--- Paper {i} ---")
        lines.append(f"paper_id: {paper.paper_id}")
        lines.append(f"title: {paper.title}")
        lines.append(f"extracted_claim: {paper.extracted_claim}")
        if paper.population_studied:
            lines.append(f"population_studied: {paper.population_studied}")
        if paper.nutritional_components:
            lines.append(f"nutritional_components: {', '.join(paper.nutritional_components)}")
    return "\n".join(lines)


def score_papers(request: ScoreRequest, model: str = DEFAULT_MODEL) -> ScoreResponse:
    """Score each paper for topical relevance."""
    response = _client().models.generate_content(
        model=model,
        contents=_build_scoring_message(request),
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=ScoreList,
            system_instruction=_SCORING_SYSTEM_PROMPT,
        ),
    )
    parsed = ScoreList.model_validate_json(response.text)
    return ScoreResponse(
        user_claim=request.user_claim,
        user_profile=request.user_profile,
        results=parsed.scores,
    )


# ---------------------------------------------------------------------------
# Step 2 — Verdict
# ---------------------------------------------------------------------------

_VERDICT_SYSTEM_PROMPT = """\
You are a biomedical evidence synthesis expert producing a final verdict on a health claim.

You will receive:
  - The user's health claim
  - The user's demographic profile
  - A list of research papers, each annotated with:
      * relevance_score (0.0–1.0)  — how topically relevant the paper is
      * stance                     — supports / contradicts / neutral / unclear
      * applies_to                 — demographic groups covered by the paper
      * demographic_match          — whether the paper's population matches the user's

VERDICT RULES:
  - Only include papers with relevance_score ≥ 0.4 in the cited lists.
  - "supported" requires at least one high-relevance (≥ 0.7) paper that supports,
    AND the relevance-weighted support mass exceeds the contradiction mass.
  - "contradicted" is the mirror.
  - Default to "insufficient_evidence" when evidence is sparse, mixed, or low-relevance.
  - confidence_percent reflects evidential strength, not the prior probability of the claim.
    A single very strong meta-analysis might warrant 85%; three weak observational studies 35%.

DEMOGRAPHIC CAVEAT:
  If most relevant evidence comes from a population that differs meaningfully from the user
  (e.g., evidence is from elderly adults but user is a child), note the gap.
  Set demographic_caveat to null if no meaningful gap exists.

Return a single JSON object matching the provided schema.
"""


def _build_verdict_message(
    user_claim: str,
    user_profile: UserProfile,
    scored: list[PaperScoreResult],
    papers_by_id: dict[str, Paper],
) -> str:
    lines = [
        f"USER CLAIM: {user_claim}",
        "",
        "USER PROFILE:",
        f"  Age: {user_profile.age if user_profile.age is not None else 'unknown'}",
        f"  Demographic group: {user_profile.demographic_group}",
        "",
        "SCORED PAPERS:",
    ]
    for s in scored:
        p = papers_by_id.get(s.paper_id)
        lines.append(f"\n--- {s.paper_id} ---")
        lines.append(f"title: {p.title if p else 'unknown'}")
        lines.append(f"url: {p.url if p and p.url else 'null'}")
        lines.append(f"relevance_score: {s.relevance_score}")
        lines.append(f"stance: {s.stance}")
        lines.append(f"applies_to: {s.applies_to}")
        lines.append(f"demographic_match: {s.demographic_match}")
        lines.append(f"extracted_claim: {p.extracted_claim if p else ''}")
    return "\n".join(lines)


def generate_verdict(
    user_claim: str,
    user_profile: UserProfile,
    scored: list[PaperScoreResult],
    papers_by_id: dict[str, Paper],
    model: str = DEFAULT_MODEL,
) -> VerdictResult:
    """Synthesise scored papers into a final verdict with confidence %."""
    response = _client().models.generate_content(
        model=model,
        contents=_build_verdict_message(
            user_claim, user_profile, scored, papers_by_id
        ),
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=VerdictResult,
            system_instruction=_VERDICT_SYSTEM_PROMPT,
        ),
    )
    return VerdictResult.model_validate_json(response.text)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def analyze_claim(request: ScoreRequest, model: str = DEFAULT_MODEL) -> AnalysisResponse:
    """Full pipeline: score → synthesize."""
    scored_response = score_papers(request, model=model)
    papers_by_id = {p.paper_id: p for p in request.papers}
    verdict = generate_verdict(
        user_claim=request.user_claim,
        user_profile=request.user_profile,
        scored=scored_response.results,
        papers_by_id=papers_by_id,
        model=model,
    )
    return AnalysisResponse(
        user_claim=request.user_claim,
        user_profile=request.user_profile,
        paper_scores=scored_response.results,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Health Myth Debunker — Paper Scorer",
    description=(
        "Scores research papers for topical relevance to a health claim, "
        "then produces a verdict (supported / contradicted / insufficient_evidence) "
        "with calibrated confidence and links to cited papers."
    ),
    version="0.3.0",
)


@app.post("/score-papers", response_model=ScoreResponse)
def score_papers_endpoint(request: ScoreRequest) -> ScoreResponse:
    try:
        return score_papers(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/analyze-claim", response_model=AnalysisResponse)
def analyze_claim_endpoint(request: ScoreRequest) -> AnalysisResponse:
    try:
        return analyze_claim(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Quick local test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_request = ScoreRequest(
        user_claim="Drinking coffee every day prevents Alzheimer's disease.",
        user_profile=UserProfile(age=45, demographic_group="adults"),
        papers=[
            Paper(
                paper_id="doi:10.1000/example1",
                title="Caffeine intake and risk of Alzheimer's disease: a meta-analysis",
                extracted_claim=(
                    "Higher habitual caffeine consumption was associated with a 27% reduced risk "
                    "of Alzheimer's disease in adults over 40."
                ),
                url="https://doi.org/10.1000/example1",
                population_studied="Adults aged 40–75",
                nutritional_components=["caffeine", "chlorogenic acid"],
            ),
            Paper(
                paper_id="doi:10.1000/example2",
                title="No protective effect of coffee on cognitive decline in older women",
                extracted_claim=(
                    "A randomised trial found no significant difference in cognitive decline "
                    "between daily coffee drinkers and non-drinkers in women aged 65+."
                ),
                url="https://doi.org/10.1000/example2",
                population_studied="Women aged 65–80",
                nutritional_components=["caffeine"],
            ),
        ],
    )
    result = analyze_claim(sample_request)
    print(json.dumps(result.model_dump(), indent=2))
