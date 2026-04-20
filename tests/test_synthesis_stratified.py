"""Tests for stratified synthesis (Patch B Task 5)."""

from __future__ import annotations

from typing import Optional

import pytest

from src.schemas import LockedPICO
from src.synthesis.schemas import (
    PaperScoreResult,
    PaperStratification,
    StratumBucket,
)
from src.synthesis.stratification import (
    build_paper_stratifications,
    build_stratum_buckets,
    compose_stratum_reasoning,
    compute_stratum_verdicts,
    detect_generalisation_warnings,
)
from src.synthesis.stratifier import ExtractedPaperValues


# ---------- helpers ----------


def _pico(
    *,
    food: Optional[str] = None,
    outcome: Optional[str] = None,
    dose: Optional[str] = None,
    form: Optional[str] = None,
    frequency: Optional[str] = None,
    population: Optional[str] = None,
) -> LockedPICO:
    return LockedPICO(
        raw_claim="",
        food=food,
        outcome=outcome,
        dose=dose,
        form=form,
        frequency=frequency,
        population=population,
    )


def _values(
    paper_id: str,
    *,
    dose: Optional[str] = None,
    form: Optional[str] = None,
    frequency: Optional[str] = None,
    population: Optional[str] = None,
) -> ExtractedPaperValues:
    return ExtractedPaperValues(
        paper_id=paper_id,
        dose_studied=dose,
        form_studied=form,
        frequency_studied=frequency,
        population_studied=population,
    )


def _score(
    paper_id: str,
    *,
    relevance: float = 0.8,
    stance: str = "supports",
) -> PaperScoreResult:
    return PaperScoreResult(
        paper_id=paper_id,
        relevance_score=relevance,
        applies_to=["adults"],
        demographic_match=True,
        stance=stance,
        reasoning="test",
    )


# ---------- build_paper_stratifications ----------


def test_build_paper_stratifications_matches_all_slots():
    pico = _pico(form="dietary", dose="500 mg/day", population="adults")
    values = {
        "A": _values("A", dose="500 mg/day", form="dietary", population="adults"),
    }
    stratifications = build_paper_stratifications(values, pico)
    assert len(stratifications) == 1
    s = stratifications[0]
    assert s.paper_id == "A"
    assert s.dose_match == "matches"
    assert s.form_match == "matches"
    assert s.population_match == "matches"
    assert s.frequency_match == "not_applicable"  # user didn't state
    assert s.overall_applicability == "direct"


def test_build_paper_stratifications_flags_mismatch_as_generalisation():
    pico = _pico(form="dietary")
    values = {"A": _values("A", form="supplement")}
    s = build_paper_stratifications(values, pico)[0]
    assert s.form_match == "different"
    assert s.overall_applicability == "generalisation"
    assert "form" in s.applicability_reasoning


def test_build_paper_stratifications_partial_when_unreported():
    pico = _pico(form="dietary", dose="500 mg")
    # Paper reports form match but doesn't report dose.
    values = {"A": _values("A", form="food", dose=None)}
    s = build_paper_stratifications(values, pico)[0]
    assert s.form_match == "matches"
    assert s.dose_match == "unreported"
    assert s.overall_applicability == "partial"


def test_applicability_reasoning_skips_slots_both_sides_silent():
    pico = _pico(form="dietary")  # only form stated
    values = {"A": _values("A", form="dietary")}
    s = build_paper_stratifications(values, pico)[0]
    # Dose, frequency, population have neither user nor paper value
    # — should not appear in the reasoning fragment.
    assert "dose" not in s.applicability_reasoning.lower()
    assert "frequency" not in s.applicability_reasoning.lower()


# ---------- build_stratum_buckets ----------


def test_stratum_buckets_only_for_user_stated_slots():
    pico = _pico(form="dietary")
    values = {
        "A": _values("A", form="dietary"),
        "B": _values("B", form="supplement"),
    }
    strat = build_paper_stratifications(values, pico)
    buckets = build_stratum_buckets([], strat, pico)
    # User stated form only → exactly one bucket.
    assert [b.slot for b in buckets] == ["form"]
    form_bucket = buckets[0]
    assert form_bucket.user_value == "dietary"
    assert form_bucket.counts.get("matches") == 1
    assert form_bucket.counts.get("different") == 1
    assert form_bucket.strata["matches"] == ["A"]
    assert form_bucket.strata["different"] == ["B"]


def test_stratum_buckets_empty_when_user_states_nothing():
    pico = _pico()
    values = {"A": _values("A", form="dietary")}
    strat = build_paper_stratifications(values, pico)
    buckets = build_stratum_buckets([], strat, pico)
    assert buckets == []


def test_stratum_buckets_dose_tiers():
    pico = _pico(dose="500 mg/day")
    values = {
        "M1": _values("M1", dose="500 mg/day"),
        "M2": _values("M2", dose="750 mg/day"),   # 1.5× → matches
        "H1": _values("H1", dose="2000 mg/day"),  # 4× → higher
        "L1": _values("L1", dose="100 mg/day"),   # 0.2× → lower
        "U1": _values("U1", dose=None),           # unreported
    }
    strat = build_paper_stratifications(values, pico)
    bucket = build_stratum_buckets([], strat, pico)[0]
    assert bucket.counts.get("matches") == 2
    assert bucket.counts.get("higher") == 1
    assert bucket.counts.get("lower") == 1
    assert bucket.counts.get("unreported") == 1


# ---------- compute_stratum_verdicts ----------


def test_stratum_verdict_supported_when_enough_supports():
    pico = _pico(form="dietary")
    values = {
        f"P{i}": _values(f"P{i}", form="dietary") for i in range(5)
    }
    strat = build_paper_stratifications(values, pico)
    bucket = build_stratum_buckets([], strat, pico)[0]
    scored = [_score(f"P{i}", stance="supports") for i in range(5)]
    verdicts = compute_stratum_verdicts(bucket, scored)
    assert verdicts["matches"] == "supported"


def test_stratum_verdict_insufficient_when_few_papers():
    pico = _pico(form="dietary")
    values = {"P1": _values("P1", form="dietary")}
    strat = build_paper_stratifications(values, pico)
    bucket = build_stratum_buckets([], strat, pico)[0]
    scored = [_score("P1", stance="supports")]
    verdicts = compute_stratum_verdicts(bucket, scored)
    assert verdicts["matches"] == "insufficient_evidence"


def test_stratum_verdict_contradicted_when_majority_contradicts():
    pico = _pico(form="dietary")
    values = {
        f"P{i}": _values(f"P{i}", form="dietary") for i in range(4)
    }
    strat = build_paper_stratifications(values, pico)
    bucket = build_stratum_buckets([], strat, pico)[0]
    scored = [_score(f"P{i}", stance="contradicts") for i in range(4)]
    verdicts = compute_stratum_verdicts(bucket, scored)
    assert verdicts["matches"] == "contradicted"


def test_stratum_verdict_insufficient_when_split():
    pico = _pico(form="dietary")
    values = {
        f"P{i}": _values(f"P{i}", form="dietary") for i in range(4)
    }
    strat = build_paper_stratifications(values, pico)
    bucket = build_stratum_buckets([], strat, pico)[0]
    scored = [
        _score("P0", stance="supports"),
        _score("P1", stance="supports"),
        _score("P2", stance="contradicts"),
        _score("P3", stance="contradicts"),
    ]
    verdicts = compute_stratum_verdicts(bucket, scored)
    assert verdicts["matches"] == "insufficient_evidence"


def test_stratum_verdict_empty_when_all_not_applicable_or_low_relevance():
    pico = _pico(form="dietary")
    values = {
        "A": _values("A", form="dietary"),
        "B": _values("B", form="dietary"),
    }
    strat = build_paper_stratifications(values, pico)
    bucket = build_stratum_buckets([], strat, pico)[0]
    scored = [
        _score("A", stance="not_applicable"),
        _score("B", relevance=0.1, stance="supports"),
    ]
    verdicts = compute_stratum_verdicts(bucket, scored)
    assert verdicts["matches"] == "empty"


# ---------- compose_stratum_reasoning ----------


def test_compose_stratum_reasoning_summarises_counts():
    pico = _pico(form="dietary")
    values = {
        "A": _values("A", form="dietary"),
        "B": _values("B", form="dietary"),
        "C": _values("C", form="supplement"),
    }
    strat = build_paper_stratifications(values, pico)
    bucket = build_stratum_buckets([], strat, pico)[0]
    scored = [
        _score("A", stance="supports"),
        _score("B", stance="supports"),
        _score("C", stance="contradicts"),
    ]
    text = compose_stratum_reasoning(bucket, scored)
    assert "2" in text["matches"]          # total papers in stratum
    assert "support" in text["matches"].lower()
    assert "1" in text["different"]


# ---------- detect_generalisation_warnings ----------


def test_no_warnings_when_all_match():
    pico = _pico(food="turmeric", form="dietary")
    stratifications = [
        PaperStratification(
            paper_id=f"P{i}", form_match="matches"
        )
        for i in range(10)
    ]
    assert detect_generalisation_warnings(stratifications, pico) == []


def test_form_warning_fires_on_majority_mismatch():
    """Spec scenario: user asked dietary but 38 of 40 retrieved papers
    study supplement. Exactly one form warning should appear."""
    pico = _pico(food="turmeric", form="dietary")
    stratifications = []
    for i in range(38):
        stratifications.append(PaperStratification(
            paper_id=f"diff{i}", form_match="different"
        ))
    for i in range(2):
        stratifications.append(PaperStratification(
            paper_id=f"match{i}", form_match="matches"
        ))
    warnings = detect_generalisation_warnings(stratifications, pico)
    assert len(warnings) == 1
    assert "turmeric" in warnings[0]
    assert "dietary" in warnings[0]
    assert "38" in warnings[0]
    assert "40" in warnings[0]


def test_dose_warning_uses_majority_direction():
    pico = _pico(food="turmeric", dose="500 mg/day")
    # 6 higher, 2 lower, 2 matches — direction should be "higher"
    stratifications = (
        [PaperStratification(paper_id=f"H{i}", dose_match="higher") for i in range(6)]
        + [PaperStratification(paper_id=f"L{i}", dose_match="lower") for i in range(2)]
        + [PaperStratification(paper_id=f"M{i}", dose_match="matches") for i in range(2)]
    )
    warnings = detect_generalisation_warnings(stratifications, pico)
    assert len(warnings) == 1
    assert "higher" in warnings[0]
    assert "500 mg/day" in warnings[0]


def test_population_warning_when_majority_different():
    pico = _pico(food="turmeric", population="pregnant women")
    stratifications = (
        [PaperStratification(paper_id=f"D{i}", population_match="different") for i in range(8)]
        + [PaperStratification(paper_id=f"M{i}", population_match="matches") for i in range(2)]
    )
    warnings = detect_generalisation_warnings(stratifications, pico)
    assert len(warnings) == 1
    assert "pregnant women" in warnings[0]


def test_multiple_warnings_concatenate():
    pico = _pico(food="turmeric", form="dietary", dose="500 mg/day")
    stratifications = [
        PaperStratification(
            paper_id=f"P{i}",
            form_match="different",
            dose_match="higher",
        )
        for i in range(10)
    ]
    warnings = detect_generalisation_warnings(stratifications, pico)
    assert len(warnings) == 2
    assert any("form" in w.lower() or "dietary" in w.lower() for w in warnings)
    assert any("higher" in w.lower() for w in warnings)


def test_no_warning_when_user_didnt_state_slot():
    # No form stated → form mismatches shouldn't create warnings.
    pico = _pico(food="turmeric")
    stratifications = [
        PaperStratification(paper_id=f"P{i}", form_match="different")
        for i in range(10)
    ]
    assert detect_generalisation_warnings(stratifications, pico) == []


# ---------- analyze_claim backward compatibility ----------


def test_verdict_result_defaults_when_locked_pico_absent():
    """Calling analyze_claim without locked_pico should produce a
    VerdictResult with empty stratification fields — no schema break
    for existing callers."""
    from src.synthesis.schemas import VerdictResult
    v = VerdictResult(
        verdict="insufficient_evidence",
        confidence_percent=50.0,
        verdict_reasoning="test",
    )
    assert v.paper_stratifications == []
    assert v.stratum_buckets == []
    assert v.generalisation_warnings == []


def test_analyze_claim_stratified_path(monkeypatch, tmp_path):
    """analyze_claim should thread locked_pico through to produce
    stratifications and warnings WITHOUT hitting the Gemini client."""
    from src.synthesis import paper_scorer
    from src.synthesis.schemas import (
        Paper,
        ScoreRequest,
        ScoreResponse,
        UserProfile,
        VerdictResult,
    )
    from src.extraction.llm_client import LLMClient

    # Two papers: one dietary (matches user form), one supplement
    # (different form → should trigger stratum "different").
    papers = [
        Paper(
            paper_id="A",
            title="Dietary turmeric meta-analysis",
            extracted_claim="Effect observed.",
            abstract=(
                "Meta-analysis of dietary turmeric intake in adults and "
                "inflammatory markers."
            ),
        ),
        Paper(
            paper_id="B",
            title="Curcumin supplement RCT",
            extracted_claim="Effect observed.",
            abstract=(
                "RCT of curcumin supplementation 500 mg twice daily for 12 "
                "weeks in adults with knee osteoarthritis."
            ),
        ),
    ]

    def fake_score(request: ScoreRequest, model: str = "m") -> ScoreResponse:
        return ScoreResponse(
            user_claim=request.user_claim,
            user_profile=request.user_profile,
            results=[
                _score("A", stance="supports"),
                _score("B", stance="supports"),
            ],
        )

    def fake_verdict(**_kwargs) -> VerdictResult:
        return VerdictResult(
            verdict="supported",
            confidence_percent=60.0,
            verdict_reasoning="Evidence supports the claim.",
        )

    monkeypatch.setattr(paper_scorer, "score_papers", fake_score)
    monkeypatch.setattr(paper_scorer, "generate_verdict", fake_verdict)

    # Scripted LLM for the stratifier extraction pass.
    import json as _json

    def provider(messages, schema, model, temperature, **kwargs):
        user = next(m["content"] for m in messages if m["role"] == "user")
        if "dietary" in user.lower() and "meta-analysis" in user.lower():
            return _json.dumps({
                "paper_id": "A",
                "dose_studied": None,
                "form_studied": "dietary",
                "frequency_studied": None,
                "population_studied": "adults",
                "extraction_reasoning": "Meta-analysis on dietary intake.",
            })
        return _json.dumps({
            "paper_id": "B",
            "dose_studied": "1000 mg/day (500 mg twice daily)",
            "form_studied": "supplement",
            "frequency_studied": "daily",
            "population_studied": "adults with knee osteoarthritis",
            "extraction_reasoning": "RCT of supplement.",
        })

    stub_llm = LLMClient(
        model="test", log_file=str(tmp_path / "strat.jsonl"),
        provider=provider,
    )

    req = ScoreRequest(
        user_claim="Does dietary turmeric help inflammation?",
        user_profile=UserProfile(age=30, demographic_group="adults"),
        papers=papers,
    )
    pico = _pico(food="turmeric", form="dietary", outcome="inflammation")

    result = paper_scorer.analyze_claim(
        req,
        locked_pico=pico,
        extractor_llm=stub_llm,
        log_file=str(tmp_path / "syn.jsonl"),
    )

    # Stratifications attached.
    assert len(result.verdict.paper_stratifications) == 2
    by_id = {s.paper_id: s for s in result.verdict.paper_stratifications}
    assert by_id["A"].form_match == "matches"
    assert by_id["B"].form_match == "different"

    # Exactly one bucket (user stated only form).
    assert len(result.verdict.stratum_buckets) == 1
    form_bucket = result.verdict.stratum_buckets[0]
    assert form_bucket.slot == "form"
    assert form_bucket.counts["matches"] == 1
    assert form_bucket.counts["different"] == 1

    # No generalisation warning at this ratio (1/2 = 50% is the min;
    # spec says >=0.5 so the warning fires).
    assert any("dietary" in w for w in result.verdict.generalisation_warnings)


def test_analyze_claim_backcompat_without_locked_pico(monkeypatch, tmp_path):
    """No locked_pico → no stratification fields, no LLM extractor used."""
    from src.synthesis import paper_scorer
    from src.synthesis.schemas import (
        Paper,
        ScoreRequest,
        ScoreResponse,
        UserProfile,
        VerdictResult,
    )

    papers = [
        Paper(paper_id="A", title="t", extracted_claim="c", abstract="a"),
    ]

    def fake_score(request, model="m"):
        return ScoreResponse(
            user_claim=request.user_claim,
            user_profile=request.user_profile,
            results=[_score("A", stance="supports")],
        )

    def fake_verdict(**_kwargs):
        return VerdictResult(
            verdict="insufficient_evidence",
            confidence_percent=50.0,
            verdict_reasoning="only one paper",
        )

    monkeypatch.setattr(paper_scorer, "score_papers", fake_score)
    monkeypatch.setattr(paper_scorer, "generate_verdict", fake_verdict)

    req = ScoreRequest(
        user_claim="x",
        user_profile=UserProfile(age=30, demographic_group="adults"),
        papers=papers,
    )
    result = paper_scorer.analyze_claim(
        req, log_file=str(tmp_path / "syn.jsonl"),
    )

    assert result.verdict.paper_stratifications == []
    assert result.verdict.stratum_buckets == []
    assert result.verdict.generalisation_warnings == []
