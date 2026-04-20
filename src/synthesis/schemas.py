"""Data models for Station 4: Synthesis.

Split out from the original ``paper_scorer.py`` so schemas and logic
live in separate modules.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Literals
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

# ---- Stratification (Patch B) ---------------------------------------------
#
# How a single paper's studied value relates to the user's stated value
# for one stratifier slot. Produced by ``src.synthesis.stratum_assigner``.
StratumMatch = Literal[
    "matches",         # paper's value matches the user's stated value
    "higher",          # paper studied more / larger than the user asked about
    "lower",           # paper studied less / smaller than the user asked about
    "different",       # categorically different (e.g., form mismatch)
    "unreported",      # paper doesn't state its value for this slot
    "not_applicable",  # user didn't state a value for this slot
]


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    """Collected by upstream agents before scoring."""
    age: int | None = Field(None, description="User age in years, if known")
    demographic_group: DemographicGroup = "unknown"


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
    population_studied: str | None = Field(
        None,
        description="Description of the study population (e.g. 'healthy adults 20–45', 'children with obesity')",
    )
    nutritional_components: list[str] = Field(
        default_factory=list,
        description="Nutritional/chemical components relevant to this paper (provided by upstream agent)",
    )
    abstract: str = Field(
        default="",
        description=(
            "Full abstract text, used by the stratifier to extract dose, form, "
            "frequency, and population values actually studied. Optional for "
            "backwards compatibility; when empty, the stratifier falls back "
            "to title + extracted_claim (thinner but not zero)."
        ),
    )


# ---------------------------------------------------------------------------
# Step 1 — Per-paper scores
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
    stance: Literal[
        "supports",
        "contradicts",
        "neutral",
        "unclear",
        "not_applicable",
    ] = Field(
        ...,
        description=(
            "Stance toward the user's claim.\n"
            "  supports       — the paper studies the SAME intervention on the SAME outcome "
            "in humans and reports an effect consistent with the claim.\n"
            "  contradicts    — same matching criteria, but effect opposite to the claim.\n"
            "  neutral        — studies the claimed intervention/outcome but finds no "
            "significant effect either way.\n"
            "  unclear        — studies the right things but conclusions are ambiguous.\n"
            "  not_applicable — studies something different (different compound, different "
            "outcome, in vitro / animal when a human claim was made, essential oils for a "
            "food claim, etc.). These do NOT count toward the verdict."
        ),
    )
    reasoning: str = Field(
        ...,
        description=(
            "Brief explanation (2-4 sentences) justifying the score and stance. "
            "If stance is not_applicable, explicitly state the intervention or outcome mismatch."
        ),
    )


class ScoreList(BaseModel):
    """Wrapper so Gemini's structured output returns a named list."""
    scores: list[PaperScoreResult]


class ScoreRequest(BaseModel):
    user_claim: str = Field(
        ...,
        description="The health claim the user wants to investigate",
    )
    user_profile: UserProfile
    papers: list[Paper] = Field(..., min_length=1)


class ScoreResponse(BaseModel):
    user_claim: str
    user_profile: UserProfile
    results: list[PaperScoreResult]


# ---------------------------------------------------------------------------
# Step 2 — Verdict
# ---------------------------------------------------------------------------

class CitedPaper(BaseModel):
    """A paper referenced in the verdict, with its link and key metadata."""
    paper_id: str
    title: str
    url: str | None = Field(None, description="Link to the paper (from input; may be null)")
    stance: Literal["supports", "contradicts", "neutral", "unclear", "not_applicable"]
    relevance_score: float
    applies_to: list[DemographicGroup]
    demographic_match: bool
    one_line_summary: str = Field(
        ...,
        description="Single sentence summarising what this paper contributes to the verdict",
    )


StratifierSlot = Literal["dose", "form", "frequency", "population"]
OverallApplicability = Literal["direct", "partial", "generalisation"]
StratumVerdict = Literal["supported", "contradicted", "insufficient_evidence", "empty"]


class PaperStratification(BaseModel):
    """How a single paper relates to the user's stated PICO values.

    Populated in Station 4 from the paper-value extractor (stratifier)
    output + the user's LockedPICO. ``overall_applicability`` is a
    compact rollup suitable for a single badge on the results UI.
    """

    paper_id: str
    dose_match: StratumMatch = "not_applicable"
    dose_studied: str | None = None
    form_match: StratumMatch = "not_applicable"
    form_studied: str | None = None
    frequency_match: StratumMatch = "not_applicable"
    frequency_studied: str | None = None
    population_match: StratumMatch = "not_applicable"
    population_studied: str | None = None
    overall_applicability: OverallApplicability = "direct"
    applicability_reasoning: str = ""


class StratumBucket(BaseModel):
    """Papers grouped by their relationship to the user's value for one slot.

    Only slots where the user stated a value produce a bucket. Each
    stratum (matches / higher / lower / different / unreported) gets a
    list of paper_ids, a count, and a mini-verdict over just that slice.
    """

    slot: StratifierSlot
    user_value: str | None
    strata: dict[StratumMatch, list[str]] = Field(default_factory=dict)
    counts: dict[StratumMatch, int] = Field(default_factory=dict)
    stratum_verdicts: dict[StratumMatch, StratumVerdict] = Field(default_factory=dict)
    stratum_reasoning: dict[StratumMatch, str] = Field(default_factory=dict)


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

    # Elicitation Patch B — stratified view. All three default to empty
    # for backwards compatibility with callers that don't pass a
    # LockedPICO into ``analyze_claim``.
    paper_stratifications: list[PaperStratification] = Field(default_factory=list)
    stratum_buckets: list[StratumBucket] = Field(default_factory=list)
    generalisation_warnings: list[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    """Full pipeline output: per-paper scores + final verdict."""
    user_claim: str
    user_profile: UserProfile
    paper_scores: list[PaperScoreResult]
    verdict: VerdictResult
