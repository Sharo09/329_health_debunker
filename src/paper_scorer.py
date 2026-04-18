"""
paper_scorer.py

Backend module for scoring research papers against a user's health claim,
then producing a final verdict with calibrated confidence.

Two-step pipeline
-----------------
Step 1 — score_papers()       : scores each paper for topical relevance (topic-based,
                                 not agreement-based) and identifies demographic fit.
Step 2 — generate_verdict()   : weighs the scored papers and emits a single verdict:
                                   "supported" | "contradicted" | "insufficient_evidence"
                                 plus a calibrated confidence percentage and a curated
                                 list of cited papers with links.

Full pipeline endpoint: POST /analyze-claim
Individual scoring only:  POST /score-papers

Designed to be called by other agents that have already:
  - Extracted the user's claim (free-text)
  - Pulled a user profile (age, demographic group, etc.)
  - Retrieved paper metadata + extracted claim/conclusion text
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Literal

import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data models — inputs
# ---------------------------------------------------------------------------

DemographicGroup = Literal[
    "infants",       # 0–1 year
    "children",      # 2–12 years
    "adolescents",   # 13–17 years
    "adults",        # 18–64 years
    "older_adults",  # 65+ years
    "general",       # not age-specific / mixed population
    "unknown",
]

Verdict = Literal["supported", "contradicted", "insufficient_evidence"]


class UserProfile(BaseModel):
    """Collected by upstream agents before scoring."""
    age: int | None = Field(None, description="User age in years, if known")
    demographic_group: DemographicGroup = "unknown"
    # Extend as your teammate's collection agent gathers more fields:
    # sex: str | None = None
    # conditions: list[str] = []


class Paper(BaseModel):
    paper_id: str = Field(..., description="Unique identifier for the paper (e.g. DOI, internal ID)")
    title: str
    extracted_claim: str = Field(
        ...,
        description=(
            "The main conclusion or claim extracted from the paper by a previous agent. "
            "Should be a concise 1-3 sentence statement of what the paper found."
        ),
    )
    url: str | None = Field(
        None,
        description="Direct URL to the paper (PubMed, journal page, DOI resolver, etc.)",
    )
    # Optional enrichment from upstream agents
    population_studied: str | None = Field(
        None,
        description="Description of the study population (e.g. 'healthy adults 20–45', 'children with obesity')",
    )
    nutritional_components: list[str] = Field(
        default_factory=list,
        description="Nutritional/chemical components relevant to this paper (provided by upstream agent)",
    )


# ---------------------------------------------------------------------------
# Data models — Step 1 output (per-paper scores)
# ---------------------------------------------------------------------------

class PaperScoreResult(BaseModel):
    paper_id: str
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "0.0 = completely unrelated to the user's claim topic; "
            "1.0 = directly addresses the exact same topic, substance, and mechanism. "
            "Score is topic-relevance only — a contradicting paper can score 1.0."
        ),
    )
    applies_to: list[DemographicGroup] = Field(
        ...,
        description="Demographic groups the paper's finding applies to, as identified by the LLM",
    )
    demographic_match: bool = Field(
        ...,
        description="True if the paper's population overlaps with the user's demographic group",
    )
    stance: Literal["supports", "contradicts", "neutral", "unclear"] = Field(
        ...,
        description=(
            "Whether the paper's conclusion supports, contradicts, or is neutral toward "
            "the user's claim. Informational only — does NOT affect relevance_score."
        ),
    )
    reasoning: str = Field(
        ...,
        description="Brief explanation (2-4 sentences) justifying the score and demographic assessment",
    )


class ScoreRequest(BaseModel):
    user_claim: str = Field(
        ...,
        description="The health claim the user wants to investigate, e.g. 'drinking coffee prevents Alzheimer's'",
    )
    user_profile: UserProfile
    papers: list[Paper] = Field(..., min_length=1)


class ScoreResponse(BaseModel):
    user_claim: str
    user_profile: UserProfile
    results: list[PaperScoreResult]


# ---------------------------------------------------------------------------
# Data models — Step 2 output (final verdict)
# ---------------------------------------------------------------------------

class CitedPaper(BaseModel):
    """A paper referenced in the verdict, with its link and key metadata."""
    paper_id: str
    title: str
    url: str | None = Field(None, description="Link to the paper (from input; may be null)")
    stance: Literal["supports", "contradicts", "neutral", "unclear"]
    relevance_score: float
    applies_to: list[DemographicGroup]
    demographic_match: bool
    one_line_summary: str = Field(
        ...,
        description="Single sentence summarising what this paper contributes to the verdict",
    )


class VerdictResult(BaseModel):
    verdict: Verdict = Field(
        ...,
        description=(
            "supported            — the weight of relevant evidence supports the claim.\n"
            "contradicted         — the weight of relevant evidence contradicts the claim.\n"
            "insufficient_evidence — relevant papers are too few, too low-quality, or too mixed "
            "to reach a clear conclusion."
        ),
    )
    confidence_percent: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description=(
            "Calibrated confidence in the verdict (0–100%). "
            "Reflects the strength, quantity, and relevance of supporting evidence — "
            "NOT how likely the claim is to be true in isolation."
        ),
    )
    verdict_reasoning: str = Field(
        ...,
        description=(
            "3-6 sentence plain-language explanation of why this verdict and confidence "
            "were assigned, including any demographic caveats."
        ),
    )
    demographic_caveat: str | None = Field(
        None,
        description=(
            "If the evidence primarily applies to a different demographic than the user, "
            "describe the gap here. Null if no meaningful gap exists."
        ),
    )
    supporting_papers: list[CitedPaper] = Field(
        default_factory=list,
        description="Papers whose conclusions support the claim (relevance_score ≥ 0.4)",
    )
    contradicting_papers: list[CitedPaper] = Field(
        default_factory=list,
        description="Papers whose conclusions contradict the claim (relevance_score ≥ 0.4)",
    )
    neutral_papers: list[CitedPaper] = Field(
        default_factory=list,
        description="Relevant papers that are neutral or inconclusive (relevance_score ≥ 0.4)",
    )


class AnalysisResponse(BaseModel):
    """Full pipeline output: per-paper scores + final verdict."""
    user_claim: str
    user_profile: UserProfile
    paper_scores: list[PaperScoreResult]
    verdict: VerdictResult


# ---------------------------------------------------------------------------
# Step 1 — Prompts & scoring logic
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

Return a JSON array. Each element must match this schema exactly:
{
  "paper_id": "<string>",
  "relevance_score": <float 0.0–1.0>,
  "applies_to": [<one or more of: "infants","children","adolescents","adults","older_adults","general","unknown">],
  "demographic_match": <true|false>,
  "stance": <"supports"|"contradicts"|"neutral"|"unclear">,
  "reasoning": "<2-4 sentence explanation>"
}

Relevance score guidance:
  0.8–1.0 : Paper directly addresses the same substance/mechanism/outcome as the claim
  0.5–0.79: Paper is on a closely related topic (e.g. same substance, different outcome)
  0.2–0.49: Paper is tangentially related (e.g. related compound, same disease different pathway)
  0.0–0.19: Paper is largely unrelated to the claim's topic

demographic_match = true if the paper's study population includes or broadly overlaps with the user's age group.
Return only the JSON array, no other text.
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


async def score_papers(request: ScoreRequest) -> ScoreResponse:
    """
    Step 1: Score each paper for topical relevance to the user's health claim.

    Relevance is topic-based only — contradicting papers are not penalised.
    The system prompt is cached so repeated calls within a session hit the cache.
    """
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _SCORING_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": _build_scoring_message(request)}],
    )

    raw = _strip_fences(response.content[0].text)
    results = [PaperScoreResult(**item) for item in json.loads(raw)]

    return ScoreResponse(
        user_claim=request.user_claim,
        user_profile=request.user_profile,
        results=results,
    )


# ---------------------------------------------------------------------------
# Step 2 — Verdict prompts & logic
# ---------------------------------------------------------------------------

_VERDICT_SYSTEM_PROMPT = """\
You are a biomedical evidence synthesis expert producing a final verdict on a health claim.

You will receive:
  - The user's health claim
  - The user's demographic profile
  - A list of research papers, each annotated with:
      * relevance_score (0.0–1.0) — how topically relevant the paper is
      * stance           — whether it supports / contradicts / is neutral toward the claim
      * applies_to       — demographic groups covered by the paper
      * demographic_match — whether the paper's population matches the user's

YOUR TASK:
  Synthesise the evidence and return a single JSON object matching this schema exactly:
  {
    "verdict": <"supported"|"contradicted"|"insufficient_evidence">,
    "confidence_percent": <float 0–100>,
    "verdict_reasoning": "<3-6 sentence plain-language explanation>",
    "demographic_caveat": "<string or null>",
    "supporting_papers": [<CitedPaper>, ...],
    "contradicting_papers": [<CitedPaper>, ...],
    "neutral_papers": [<CitedPaper>, ...]
  }

  Where each CitedPaper is:
  {
    "paper_id": "<string>",
    "title": "<string>",
    "url": "<string or null>",
    "stance": <"supports"|"contradicts"|"neutral"|"unclear">,
    "relevance_score": <float>,
    "applies_to": [<demographic groups>],
    "demographic_match": <true|false>,
    "one_line_summary": "<single sentence contribution to verdict>"
  }

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
  Set to null if no meaningful gap exists.

Return only the JSON object, no other text.
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


async def generate_verdict(
    user_claim: str,
    user_profile: UserProfile,
    scored: list[PaperScoreResult],
    papers_by_id: dict[str, Paper],
) -> VerdictResult:
    """
    Step 2: Synthesise scored papers into a final verdict with confidence percentage
    and curated cited-paper lists (with links).
    """
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _VERDICT_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": _build_verdict_message(
                    user_claim, user_profile, scored, papers_by_id
                ),
            }
        ],
    )

    raw = _strip_fences(response.content[0].text)
    data = json.loads(raw)
    return VerdictResult(**data)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

async def analyze_claim(request: ScoreRequest) -> AnalysisResponse:
    """
    Full two-step pipeline:
      1. Score each paper for topical relevance.
      2. Synthesise scores into a verdict with confidence % and paper links.
    """
    # Run scoring (Step 1)
    scored_response = await score_papers(request)

    # Build a lookup so the verdict step can attach titles/URLs
    papers_by_id = {p.paper_id: p for p in request.papers}

    # Generate verdict (Step 2)
    verdict = await generate_verdict(
        user_claim=request.user_claim,
        user_profile=request.user_profile,
        scored=scored_response.results,
        papers_by_id=papers_by_id,
    )

    return AnalysisResponse(
        user_claim=request.user_claim,
        user_profile=request.user_profile,
        paper_scores=scored_response.results,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove markdown code fences if the model wraps JSON in them."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Health Myth Debunker — Paper Scorer",
    description=(
        "Scores research papers for topical relevance to a health claim, "
        "then produces a verdict (supported / contradicted / insufficient_evidence) "
        "with calibrated confidence and links to cited papers."
    ),
    version="0.2.0",
)


@app.post("/score-papers", response_model=ScoreResponse)
async def score_papers_endpoint(request: ScoreRequest) -> ScoreResponse:
    """
    Step 1 only: score each paper for topical relevance.
    Use /analyze-claim for the full pipeline including the final verdict.
    """
    try:
        return await score_papers(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/analyze-claim", response_model=AnalysisResponse)
async def analyze_claim_endpoint(request: ScoreRequest) -> AnalysisResponse:
    """
    Full pipeline: score papers, then produce a verdict with confidence % and paper links.

    Called by other agents after they have:
      1. Collected the user's claim and profile (age, demographic group, etc.)
      2. Identified nutritional/chemical components relevant to the claim
      3. Retrieved candidate papers, extracted their conclusions, and resolved their URLs
    """
    try:
        return await analyze_claim(request)
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
            Paper(
                paper_id="doi:10.1000/example3",
                title="Sugar-sweetened beverages and childhood obesity",
                extracted_claim=(
                    "Consumption of sugar-sweetened beverages more than once daily was "
                    "strongly associated with obesity in children aged 6–12."
                ),
                url="https://doi.org/10.1000/example3",
                population_studied="Children aged 6–12",
                nutritional_components=["sucrose", "fructose"],
            ),
        ],
    )

    async def _run() -> None:
        result = await analyze_claim(sample_request)
        print(json.dumps(result.model_dump(), indent=2))

    asyncio.run(_run())
