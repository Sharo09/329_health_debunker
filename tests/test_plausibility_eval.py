"""Hand-labelled plausibility eval set (Task 8 of plausibility_spec).

Two test kinds:

1. ``test_plausibility_eval_f1_deterministic`` — always runs. Exercises
   the F1 checker (pure arithmetic) against every fixture row that
   supplies ``food`` and ``dose``. No LLM needed.

2. ``test_plausibility_eval_full_agent`` — gated on
   ``RUN_LIVE_PLAUSIBILITY_EVAL=1``. Hits the real Gemini API for the
   mechanism check; spec target is ≥85% overall agreement with the
   hand-labelled ``expected_should_proceed``.

The fixture lives at ``tests/fixtures/plausibility_test_claims.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.plausibility.dose_checker import check_dose_plausibility, parse_dose
from src.plausibility.plausibility_agent import PlausibilityAgent
from src.plausibility.reference_table import ReferenceTable
from src.plausibility.schemas import ParsedDose
from src.schemas import PartialPICO


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "plausibility_test_claims.yaml"


def _load_cases() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        cases = yaml.safe_load(fh)
    assert isinstance(cases, list) and cases, "fixture must be a non-empty list"
    return cases


def _pico_for(case: dict[str, Any]) -> PartialPICO:
    return PartialPICO(
        raw_claim=case["claim"],
        food=case.get("food"),
        dose=case.get("dose"),
        component=case.get("component"),
        outcome=case.get("outcome"),
    )


# ---------- sanity ----------


def test_fixture_shape():
    cases = _load_cases()
    assert 40 <= len(cases) <= 120, f"fixture size {len(cases)} outside spec band"

    kinds = {"F1_dose": 0, "F2_feasibility": 0, "F3_mechanism": 0, "F4_frame": 0}
    clean = 0
    for c in cases:
        assert "claim" in c and isinstance(c["claim"], str) and c["claim"].strip()
        fs = c.get("expected_failures") or []
        sevs = c.get("expected_severities") or []
        assert len(fs) == len(sevs), f"failures/severities length mismatch: {c['claim']}"
        for f, s in zip(fs, sevs):
            assert f in kinds, f"unknown failure type {f!r}"
            assert s in ("blocking", "warning"), f"unknown severity {s!r}"
            kinds[f] += 1
        should_proceed = c["expected_should_proceed"]
        assert isinstance(should_proceed, bool)
        has_block = any(s == "blocking" for s in sevs)
        assert should_proceed == (not has_block), (
            f"inconsistent label: {c['claim']!r}"
        )
        if not fs:
            clean += 1

    # Loose sanity on the distribution target in the spec (Task 8).
    assert kinds["F1_dose"] >= 10
    assert kinds["F2_feasibility"] >= 5
    assert kinds["F3_mechanism"] >= 5
    assert kinds["F4_frame"] >= 3
    assert clean >= 15


# ---------- deterministic F1 (no LLM) ----------


def _f1_rows() -> list[dict[str, Any]]:
    """Rows that exercise F1 — must have a food and a numeric dose.

    We also include any row whose only expected failure is F1 so a "clean"
    expectation (no F1 firing) is testable when the dose is provided.
    """
    out = []
    for c in _load_cases():
        if not c.get("food") or not c.get("dose"):
            continue
        # Skip rows where expected failures include non-F1 items — we
        # can't evaluate F3/F4 deterministically. But we can still check
        # that F1 fires or not in the expected way on dose rows.
        out.append(c)
    assert out, "no F1 rows found in fixture"
    return out


def _parse_numeric_and_unit(dose_text: str) -> tuple[float | None, str | None]:
    """Hand-rolled dose parser good enough for the fixture's strings.

    The live ``parse_dose`` uses an LLM; for the deterministic test we
    extract a number and a unit token from strings like "100 per day",
    "50000 IU per day", "1 gallon per day". Falls back to ``(None, None)``
    for vague strings like "a lot".
    """
    import re

    s = dose_text.strip().lower()
    # Strip trailing "per <x>" — time basis isn't needed for the arithmetic.
    s = re.sub(r"per\s+(day|week|meal|month|year)\b.*$", "", s).strip()
    m = re.match(r"^([\d.]+)\s*([a-zA-Z]+)?$", s)
    if not m:
        # Something like "1 gallon" — try a looser pattern.
        m2 = re.match(r"^([\d.]+)\s+([a-zA-Z]+).*$", s)
        if not m2:
            return None, None
        return float(m2.group(1)), m2.group(2)
    val = float(m.group(1))
    unit = m.group(2)
    return val, unit


@pytest.mark.parametrize("case", _f1_rows(), ids=lambda c: c["claim"][:60])
def test_plausibility_eval_f1_deterministic(case):
    """Every row that supplies food+dose: the F1 checker must agree with the label."""
    table = ReferenceTable()
    val, unit = _parse_numeric_and_unit(case["dose"])
    parsed = ParsedDose(
        numeric_value=val,
        unit=unit,
        time_basis="per day",
        confidence="high" if val is not None else "not_a_dose",
        raw_source=case["dose"],
    )
    result = check_dose_plausibility(case["food"], parsed, table)

    expected_f1 = [
        (t, s)
        for t, s in zip(case["expected_failures"], case["expected_severities"])
        if t == "F1_dose"
    ]

    if expected_f1:
        assert result is not None, (
            f"expected F1 to fire for {case['claim']!r} but it did not"
        )
        assert result.failure_type == "F1_dose"
        expected_severity = expected_f1[0][1]
        assert result.severity == expected_severity, (
            f"{case['claim']!r}: expected severity {expected_severity} "
            f"but got {result.severity}"
        )
    else:
        # Not expecting an F1 finding on this row (either food not in
        # reference table, dose below implausible threshold, or unit
        # unrecognised — all three are valid "F1 silent" outcomes).
        assert result is None, (
            f"F1 fired unexpectedly on {case['claim']!r}: "
            f"{result.failure_type} / {result.severity}"
        )


# ---------- full agent (live LLM) ----------


_RUN_LIVE = os.getenv("RUN_LIVE_PLAUSIBILITY_EVAL") == "1"


@pytest.mark.skipif(
    not _RUN_LIVE,
    reason="live-LLM eval — set RUN_LIVE_PLAUSIBILITY_EVAL=1 to run (needs GEMINI_API_KEY)",
)
def test_plausibility_eval_full_agent(tmp_path):
    """Run every fixture row through the real agent; assert ≥85% agreement.

    Spec target is 85% overall and 95%+ on F1; the deterministic test
    above covers the F1 bar. This test backs up the LLM-driven rows.
    """
    from src.extraction.llm_client import LLMClient

    cases = _load_cases()
    agent = PlausibilityAgent(
        llm_client=LLMClient(model=os.getenv("LIVE_LLM_MODEL", "gemini-2.5-flash")),
        log_file=str(tmp_path / "eval.jsonl"),
    )

    hits = 0
    misses: list[tuple[str, bool, bool]] = []
    for case in cases:
        pico = _pico_for(case)
        result = agent.evaluate(pico)
        expected = case["expected_should_proceed"]
        if result.should_proceed_to_pipeline == expected:
            hits += 1
        else:
            misses.append(
                (case["claim"], expected, result.should_proceed_to_pipeline)
            )

    accuracy = hits / len(cases)
    print(f"\nPlausibility live-eval accuracy: {accuracy:.1%} ({hits}/{len(cases)})")
    for claim, want, got in misses[:20]:
        print(f"  miss: want={want} got={got}  :: {claim[:80]}")
    assert accuracy >= 0.85, f"accuracy {accuracy:.1%} below 85% target"
