"""Eval-runner for the stratification fixture (Patch B Task 7).

Loads ``tests/fixtures/stratification_test_cases.yaml`` and, for each
case, drives the deterministic pieces of the stratified synthesis
pipeline (no LLM): build_paper_stratifications → build_stratum_buckets
→ compute_stratum_verdicts → detect_generalisation_warnings.

Asserts stratum counts exactly (which is the core property this fixture
exists to pin down) and asserts warnings contain expected substrings
(phrasing may drift, counts must not).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.schemas import LockedPICO
from src.synthesis.schemas import PaperScoreResult, StratumMatch
from src.synthesis.stratification import (
    build_paper_stratifications,
    build_stratum_buckets,
    compute_stratum_verdicts,
    detect_generalisation_warnings,
)
from src.synthesis.stratifier import ExtractedPaperValues


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "stratification_test_cases.yaml"
)


def _load_cases() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        cases = yaml.safe_load(fh)
    assert isinstance(cases, list) and cases
    # Each case needs a unique ``name`` — duplicated names silently
    # hide bugs when the parametrised test ids collide.
    names = [c["name"] for c in cases]
    assert len(names) == len(set(names)), "duplicate case name in fixture"
    return cases


def _pico_from_case(pico_block: dict[str, Any]) -> LockedPICO:
    return LockedPICO(
        raw_claim=pico_block.get("raw_claim", ""),
        food=pico_block.get("food"),
        outcome=pico_block.get("outcome"),
        dose=pico_block.get("dose"),
        form=pico_block.get("form"),
        frequency=pico_block.get("frequency"),
        population=pico_block.get("population"),
    )


def _extracted_values_from_case(papers_block: list[dict[str, Any]]):
    out: dict[str, ExtractedPaperValues] = {}
    for entry in papers_block:
        ev = entry.get("extracted_values") or {}
        out[entry["paper_id"]] = ExtractedPaperValues(
            paper_id=entry["paper_id"],
            dose_studied=ev.get("dose_studied"),
            form_studied=ev.get("form_studied"),
            frequency_studied=ev.get("frequency_studied"),
            population_studied=ev.get("population_studied"),
        )
    return out


def _scored_from_case(papers_block: list[dict[str, Any]]) -> list[PaperScoreResult]:
    scored = []
    for entry in papers_block:
        scored.append(PaperScoreResult(
            paper_id=entry["paper_id"],
            relevance_score=float(entry.get("relevance_score", 0.8)),
            applies_to=["adults"],
            demographic_match=True,
            stance=entry["stance"],
            reasoning="fixture",
        ))
    return scored


# ---------- parametrised runner ----------


_CASES = _load_cases()


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["name"])
def test_stratification_case(case):
    pico = _pico_from_case(case["locked_pico"])
    papers = case["papers"]
    extracted = _extracted_values_from_case(papers)
    scored = _scored_from_case(papers)

    stratifications = build_paper_stratifications(extracted, pico)
    buckets = build_stratum_buckets(scored, stratifications, pico)

    # ---- expected stratum counts (exact match) ----
    expected_counts = case["expected"].get("stratum_counts") or {}

    # Map slot → bucket for easier lookup.
    bucket_by_slot = {b.slot: b for b in buckets}

    # When expected slot has no counts, user didn't state that slot — no
    # bucket should exist.
    for slot in ("dose", "form", "frequency", "population"):
        if slot in expected_counts:
            assert slot in bucket_by_slot, (
                f"{case['name']}: expected bucket for slot {slot} but none built"
            )
            actual = dict(bucket_by_slot[slot].counts)
            # Strip any strata not mentioned in expected to make the
            # comparison strict on the ones we named. Any unexpected
            # stratum with count > 0 will surface as a diff.
            expected = dict(expected_counts[slot])
            assert actual == expected, (
                f"{case['name']}: slot {slot} count mismatch\n"
                f"  expected: {expected}\n"
                f"  actual:   {actual}"
            )
        else:
            assert slot not in bucket_by_slot, (
                f"{case['name']}: bucket unexpectedly built for {slot} "
                f"(user didn't state a value)"
            )

    # ---- generalisation warnings (substring checks) ----
    warnings = detect_generalisation_warnings(stratifications, pico)
    expected_substrings = case["expected"].get("generalisation_warnings") or []
    if not expected_substrings:
        assert warnings == [], (
            f"{case['name']}: expected no warnings but got {warnings!r}"
        )
    else:
        joined = " | ".join(warnings)
        for expected_sub in expected_substrings:
            assert expected_sub in joined, (
                f"{case['name']}: expected warning substring "
                f"{expected_sub!r} not found in {warnings!r}"
            )

    # ---- stratum-level verdicts (optional) ----
    expected_verdicts = case["expected"].get("stratum_verdicts") or {}
    for slot, per_stratum in expected_verdicts.items():
        assert slot in bucket_by_slot, (
            f"{case['name']}: stratum_verdicts given for slot {slot} "
            f"but no bucket was built"
        )
        bucket = bucket_by_slot[slot]
        actual = compute_stratum_verdicts(bucket, scored)
        for stratum, expected_verdict in per_stratum.items():
            stratum_key: StratumMatch = stratum  # type: ignore[assignment]
            assert actual.get(stratum_key) == expected_verdict, (
                f"{case['name']}: slot {slot} stratum {stratum} — "
                f"expected verdict {expected_verdict!r} but got "
                f"{actual.get(stratum_key)!r}"
            )

    # ---- applicability rollup counts (optional) ----
    expected_app = case["expected"].get("applicability_counts")
    if expected_app:
        rollup = Counter(s.overall_applicability for s in stratifications)
        for bucket, want in expected_app.items():
            assert rollup.get(bucket, 0) == want, (
                f"{case['name']}: applicability[{bucket}] — "
                f"expected {want} got {rollup.get(bucket, 0)}"
            )


# ---------- sanity tests on the fixture itself ----------


def test_fixture_has_enough_cases():
    # Spec asks for 30+; leave some slack for future additions.
    assert len(_CASES) >= 30, f"only {len(_CASES)} cases, need ≥30"


def test_fixture_covers_spec_scenarios():
    """The spec's Task 7 lists five must-have scenarios."""
    names = {c["name"] for c in _CASES}
    assert "all-four-slots-stated-mixed" in names
    assert "dose-only-stated" in names
    assert "turmeric-dietary-minority-fires-form-warning" in names
    assert "dose-higher-than-all-papers" in names
    assert "pregnant-t1d-narrow-intersection" in names
