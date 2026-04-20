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
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

DEFAULT_LOG_FILE = "logs/synthesis.jsonl"

from pydantic import BaseModel, Field

from src.synthesis.schemas import (
    AnalysisResponse,
    CitedPaper,
    Paper,
    PaperScoreResult,
    PaperStratification,
    ScoreList,
    ScoreRequest,
    ScoreResponse,
    StratumBucket,
    UserProfile,
    Verdict,
    VerdictResult,
)


# Narrow subset of VerdictResult used as Gemini's response schema.
# Gemini rejects ``additionalProperties`` in the JSON schema, which
# Pydantic emits for every ``dict[K, V]`` field. ``StratumBucket`` has
# four such dicts, so including ``stratum_buckets`` in the LLM-facing
# schema fails. We compute the Patch B fields deterministically after
# the LLM returns and splice them onto the full VerdictResult.
class _VerdictResultLLM(BaseModel):
    verdict: Verdict
    confidence_percent: float
    verdict_reasoning: str
    demographic_caveat: str | None = None
    supporting_papers: list[CitedPaper] = Field(default_factory=list)
    contradicting_papers: list[CitedPaper] = Field(default_factory=list)
    neutral_papers: list[CitedPaper] = Field(default_factory=list)
from src.synthesis.stratification import (
    build_paper_stratifications,
    build_stratum_buckets,
    compose_stratum_reasoning,
    compute_stratum_verdicts,
    detect_generalisation_warnings,
)
from src.synthesis.stratifier import extract_values_in_parallel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gemini-3.1-pro-preview"

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
You are a biomedical research analyst. For each paper, you assign a
relevance score AND a stance label toward the user's claim.

TWO RULES YOU MUST NOT CONFLATE
================================

RULE 1 — relevance_score is about TOPIC SIMILARITY, not agreement.
A paper that CONTRADICTS the claim is just as relevant as one that
supports it, if it studies the same intervention on the same outcome.
Never lower the score because the paper disagrees.

RULE 2 — stance has a strict match test.  For a paper to count as
"supports" / "contradicts" / "neutral" / "unclear", the paper MUST study:

  (a) THE CLAIMED INTERVENTION — the same food/compound/form as the claim.
      • Claim says "eating an orange" → a paper about orange ESSENTIAL OIL
        does NOT match. A paper on vitamin C supplements is a different
        intervention than dietary orange, but is acceptable as a mechanism
        match IF the user's PICO explicitly names vitamin C as the component.
      • A paper on a DIFFERENT plant ("rockrose", "guava flavonoids",
        "essential oils" in general) is NOT a match.
      • A paper on extracts of a NON-EDIBLE part of the food (orange peel
        compounds used in vaccine adjuvants) is NOT a match for a
        dietary claim.

  (b) THE CLAIMED OUTCOME — and in a setting applicable to the claim.
      • Claim is about preventing or treating a disease in humans → the
        paper needs a clinical / epidemiological outcome in humans.
      • In vitro enzyme-binding, molecular docking, computational models,
        in silico studies, animal-only studies, or diagnostic-tool /
        sensor / surveillance papers do NOT test the prevention claim.
      • A review of a different topic that merely mentions the food in
        passing does NOT count.

  (c) CONSISTENCY WITH THE CLAIMED DIRECTION for "supports" / "contradicts":
      • "supports" requires the paper to report an effect in the direction
        the claim asserts. If the claim is "X prevents Y" and the paper
        says "X may reduce Y risk", supports. If "X has no effect on Y",
        contradicts or neutral depending on the effect size.

If ANY of (a), (b), (c) fail, the stance MUST be "not_applicable".
Papers with stance="not_applicable" will be DROPPED from the verdict
computation downstream — they are not evidence.

CALIBRATION EXAMPLES
====================

Claim: "Does eating an orange prevent flu?"

 • Cochrane review "Vitamin C for preventing and treating the common cold"
   — intervention=vitamin C (matches PICO component), outcome=common cold
   / URI (adjacent to flu), humans. → relevance=0.85,
   stance=supports/contradicts depending on finding.

 • RCT "Daily orange juice consumption and incidence of colds in children"
   — intervention=orange juice (dietary), outcome=colds, humans. →
   relevance=0.95, stance=depends on finding.

 • In silico "Flavanones in citrus peel bind to influenza neuraminidase"
   — intervention=isolated compounds from inedible peel, outcome=enzyme
   binding (not disease prevention), not human. → relevance=0.30,
   stance=not_applicable (wrong intervention AND wrong outcome setting).

 • Review "CYSTUS052 rockrose extract against flu"
   — intervention=rockrose (different plant entirely). → relevance=0.10,
   stance=not_applicable.

 • Paper "Essential oils as antimicrobial agents in food preservation"
   — intervention=essential oils (not dietary consumption of fruit), and
   the outcome is food preservation, not human flu. → relevance=0.10,
   stance=not_applicable.

 • Surveillance paper "Diagnostic accuracy of rapid flu tests"
   — doesn't involve the food at all. → relevance=0.05,
   stance=not_applicable.

RELEVANCE SCORE GUIDE
=====================
  0.8–1.0 : studies the SAME intervention on the SAME outcome in humans
  0.5–0.79: related intervention (known mechanism compound) on same outcome
  0.2–0.49: tangentially related (different compound, same disease area)
  0.0–0.19: largely unrelated

demographic_match = true if the paper's study population overlaps with
the user's age group.

Return a JSON object matching the provided schema. The ``scores`` field
must contain one entry per paper, IN THE SAME ORDER as the input.
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
            # Structured scoring against a clear rubric — no thinking pass needed.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
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
  - A list of scored papers. Each paper has:
      * relevance_score (0.0–1.0)  — topical relevance
      * stance                     — supports / contradicts / neutral / unclear / not_applicable
      * applies_to                 — demographic groups the finding applies to
      * demographic_match          — overlaps the user's population

HARD FILTERING RULES (apply BEFORE thinking about the verdict)
==============================================================

1. DROP every paper with stance="not_applicable". These studied a
   different intervention or a different outcome; they are NOT evidence
   for or against the claim. They do not appear in supporting_papers,
   contradicting_papers, or neutral_papers. Do not mention them in
   verdict_reasoning except optionally as "N papers were retrieved but
   studied a different intervention and were excluded."

2. DROP every paper with relevance_score < 0.4. Low-relevance papers
   are noise.

After these filters, compute the verdict ONLY from the remaining
supports / contradicts / neutral / unclear papers.

VERDICT RULES
=============

  - "supported" requires at least one high-relevance (≥ 0.7) paper
    with stance="supports", AND the relevance-weighted support mass
    strictly exceeds the contradiction mass. If the highest-quality
    evidence (systematic reviews, meta-analyses, RCTs) contradicts,
    do NOT vote "supported" just because there are more observational
    papers on the other side.
  - "contradicted" is the mirror.
  - "insufficient_evidence" is the default when:
      * <2 papers remain after filtering, OR
      * remaining papers are all neutral/unclear, OR
      * evidence is split with no tier-1 tie-breaker.

  - confidence_percent reflects evidential strength, not prior
    probability of the claim. A single Cochrane review against, with
    nothing opposing it, warrants ~80%. Mixed low-quality evidence
    warrants ~35%.

  - CONFIDENCE CEILINGS (do not exceed without meeting the criterion):
      * ≥80 — ONLY if ≥1 systematic review or meta-analysis AND ≥3 other
              tier-2+ studies (RCTs, large cohorts) pointing the same way.
      * 60–79 — ≥1 SR/meta-analysis OR ≥3 consistent RCTs.
      * 40–59 — ≥3 consistent observational/pilot studies, OR mixed
              signals where majority supports.
      * ≤39 — 1–2 papers surviving the filter; evidence base is too
              thin to be confident either way regardless of direction.

    A verdict built on only 3–4 small/pilot/preliminary studies CANNOT
    be ≥80% confident, even if they all point the same way.

DEMOGRAPHIC CAVEAT
==================
  If most relevant evidence comes from a population that differs
  meaningfully from the user (e.g., evidence is from elderly adults
  but user is a child), note the gap. Set demographic_caveat=null
  if no meaningful gap exists.

STRATIFIED EVIDENCE (Patch B)
=============================
When the user stated a specific dose / form / frequency / population,
papers are pre-labelled with how they relate to the user's stated
value (matches / higher / lower / different / unreported). Each
paper's label for each slot is listed in its block below when
available.

Weighting rule: papers in the "matches" stratum for the user's
stated slot value are the most directly applicable. When papers in
the matching stratum disagree with papers in other strata, the
matching stratum wins FOR THE USER'S SPECIFIC CLAIM. Mention this
explicitly in verdict_reasoning when it happens — e.g. "studies at
dietary doses support the claim; studies at pharmacological
supplement doses contradict, but the latter don't address the
user's question."

When generalisation warnings are provided, weave the worst one into
verdict_reasoning so the user sees why matching-stratum evidence
may be thin.

Return a single JSON object matching the provided schema.
"""


def _build_verdict_message(
    user_claim: str,
    user_profile: UserProfile,
    scored: list[PaperScoreResult],
    papers_by_id: dict[str, Paper],
    stratifications: list[PaperStratification] | None = None,
    generalisation_warnings: list[str] | None = None,
    user_pico_summary: str | None = None,
) -> str:
    lines = [
        f"USER CLAIM: {user_claim}",
        "",
        "USER PROFILE:",
        f"  Age: {user_profile.age if user_profile.age is not None else 'unknown'}",
        f"  Demographic group: {user_profile.demographic_group}",
    ]
    if user_pico_summary:
        lines.extend(["", "USER STATED VALUES:", f"  {user_pico_summary}"])

    if generalisation_warnings:
        lines.append("")
        lines.append("GENERALISATION WARNINGS:")
        for w in generalisation_warnings:
            lines.append(f"  - {w}")

    strat_by_id: dict[str, PaperStratification] = {}
    if stratifications:
        strat_by_id = {s.paper_id: s for s in stratifications}

    lines.extend(["", "SCORED PAPERS:"])
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
        strat = strat_by_id.get(s.paper_id)
        if strat is not None:
            lines.append(
                f"strata: dose={strat.dose_match}, form={strat.form_match}, "
                f"frequency={strat.frequency_match}, population={strat.population_match}"
            )
            lines.append(f"overall_applicability: {strat.overall_applicability}")
    return "\n".join(lines)


def _user_pico_summary(locked_pico) -> str | None:
    """Render the stratifier slots the user actually answered."""
    if locked_pico is None:
        return None
    parts: list[str] = []
    for slot in ("dose", "form", "frequency", "population"):
        val = getattr(locked_pico, slot, None)
        if val:
            parts.append(f"{slot}={val}")
    return "; ".join(parts) if parts else None


def generate_verdict(
    user_claim: str,
    user_profile: UserProfile,
    scored: list[PaperScoreResult],
    papers_by_id: dict[str, Paper],
    model: str = DEFAULT_MODEL,
    enable_thinking: bool = True,
    stratifications: list[PaperStratification] | None = None,
    generalisation_warnings: list[str] | None = None,
    locked_pico=None,
) -> VerdictResult:
    """Synthesise scored papers into a final verdict with confidence %.

    Verdict synthesis benefits from reasoning across papers — keep
    thinking enabled by default. Set ``enable_thinking=False`` to trade
    some nuance for ~30% faster response.

    When ``stratifications`` / ``generalisation_warnings`` / ``locked_pico``
    are provided (Patch B), the verdict prompt sees per-paper stratum
    labels and the explicit user-stated slot values so it can weight
    matching-stratum papers more heavily.
    """
    config_kwargs = dict(
        temperature=0.0,
        response_mime_type="application/json",
        # Narrow schema — stratification fields are populated in
        # analyze_claim *after* this call. See _VerdictResultLLM above.
        response_schema=_VerdictResultLLM,
        system_instruction=_VERDICT_SYSTEM_PROMPT,
    )
    if not enable_thinking:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

    response = _client().models.generate_content(
        model=model,
        contents=_build_verdict_message(
            user_claim, user_profile, scored, papers_by_id,
            stratifications=stratifications,
            generalisation_warnings=generalisation_warnings,
            user_pico_summary=_user_pico_summary(locked_pico),
        ),
        config=types.GenerateContentConfig(**config_kwargs),
    )
    core = _VerdictResultLLM.model_validate_json(response.text)
    # Expand into the full VerdictResult; Patch B list fields default
    # to empty and get overwritten by analyze_claim.
    return VerdictResult(**core.model_dump())


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def analyze_claim(
    request: ScoreRequest,
    model: str = DEFAULT_MODEL,
    log_file: str | None = None,
    locked_pico=None,
    extractor_llm=None,
) -> AnalysisResponse:
    """Full pipeline: score → stratify → synthesize.

    When ``locked_pico`` is provided, Station 1.5+2 stratifier slot
    values drive a per-paper value extraction (LLM) + deterministic
    stratum assignment + generalisation warnings. The resulting
    stratifications, stratum buckets, and warnings are attached to
    the verdict so the results UI can render the stratified view.

    When ``locked_pico`` is None (back-compat), the pipeline behaves
    exactly as before: score → verdict, with empty stratification
    fields on the verdict object.

    ``extractor_llm`` is an optional ``LLMClient`` used for the
    stratifier extraction pass. Defaults to a fresh Gemini Flash
    client with thinking disabled — cheap, fast, bounded.
    """
    scored_response = score_papers(request, model=model)
    papers_by_id = {p.paper_id: p for p in request.papers}

    stratifications: list[PaperStratification] = []
    buckets: list[StratumBucket] = []
    warnings: list[str] = []

    if locked_pico is not None:
        from src.extraction.llm_client import LLMClient as _LLMClient
        llm = extractor_llm or _LLMClient(
            model=model, thinking_budget=0
        )
        extracted_values = extract_values_in_parallel(
            request.papers, llm, max_workers=4
        )
        stratifications = build_paper_stratifications(
            extracted_values, locked_pico
        )
        buckets = build_stratum_buckets(
            scored_response.results, stratifications, locked_pico
        )
        for b in buckets:
            b.stratum_verdicts = compute_stratum_verdicts(
                b, scored_response.results
            )
            b.stratum_reasoning = compose_stratum_reasoning(
                b, scored_response.results
            )
        warnings = detect_generalisation_warnings(
            stratifications, locked_pico
        )

    verdict = generate_verdict(
        user_claim=request.user_claim,
        user_profile=request.user_profile,
        scored=scored_response.results,
        papers_by_id=papers_by_id,
        model=model,
        stratifications=stratifications or None,
        generalisation_warnings=warnings or None,
        locked_pico=locked_pico,
    )
    # Attach the stratified view to the verdict object for the UI to
    # render. The VerdictResult literal returned by the LLM defaults
    # these fields to empty lists; we overwrite with our deterministic
    # computation.
    verdict.paper_stratifications = stratifications
    verdict.stratum_buckets = buckets
    verdict.generalisation_warnings = warnings

    result = AnalysisResponse(
        user_claim=request.user_claim,
        user_profile=request.user_profile,
        paper_scores=scored_response.results,
        verdict=verdict,
    )
    _log_synthesis(result, papers_by_id, log_file or DEFAULT_LOG_FILE, model)
    return result


def _log_synthesis(
    result: AnalysisResponse,
    papers_by_id: dict[str, Paper],
    log_file: str,
    model: str,
) -> None:
    """Append one JSONL record capturing every score + the final verdict."""
    # Tally stances to surface at a glance.
    stance_counts: dict[str, int] = {}
    for s in result.paper_scores:
        stance_counts[s.stance] = stance_counts.get(s.stance, 0) + 1

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "user_claim": result.user_claim,
        "user_profile": result.user_profile.model_dump(),
        "verdict": result.verdict.verdict,
        "confidence_percent": result.verdict.confidence_percent,
        "demographic_caveat": result.verdict.demographic_caveat,
        "verdict_reasoning": result.verdict.verdict_reasoning,
        "papers_scored": len(result.paper_scores),
        "stance_counts": stance_counts,
        # Full per-paper scores — the crucial data for diagnosing
        # "why did this verdict come out this way?".
        "paper_scores": [
            {
                **s.model_dump(),
                "title": (papers_by_id.get(s.paper_id).title
                          if s.paper_id in papers_by_id else None),
            }
            for s in result.paper_scores
        ],
        "cited_supporting": [p.paper_id for p in result.verdict.supporting_papers],
        "cited_contradicting": [p.paper_id for p in result.verdict.contradicting_papers],
        "cited_neutral": [p.paper_id for p in result.verdict.neutral_papers],
        # Patch B — audit trail for stratified synthesis. Empty when
        # analyze_claim ran without a locked_pico.
        "stratifications": [
            s.model_dump() for s in result.verdict.paper_stratifications
        ],
        "stratum_buckets": [
            b.model_dump() for b in result.verdict.stratum_buckets
        ],
        "generalisation_warnings": list(result.verdict.generalisation_warnings),
    }
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


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
