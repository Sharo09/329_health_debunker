"""Schema tests for Station 1.5 (Plausibility)."""

import pytest

from src.plausibility.schemas import (
    ParsedDose,
    PlausibilityFailure,
    PlausibilityResult,
)


def test_parsed_dose_defaults():
    d = ParsedDose(raw_source="100 apples per day")
    assert d.numeric_value is None
    assert d.unit is None
    assert d.time_basis is None
    assert d.confidence == "not_a_dose"
    assert d.raw_source == "100 apples per day"


def test_plausibility_failure_requires_fields():
    with pytest.raises(Exception):
        PlausibilityFailure(failure_type="F1_dose", severity="blocking")  # type: ignore[call-arg]

    f = PlausibilityFailure(
        failure_type="F1_dose", severity="blocking", reasoning="ok"
    )
    assert f.supporting_data == {}


def test_should_proceed_true_when_no_failures():
    res = PlausibilityResult()
    assert res.should_proceed_to_pipeline is True


def test_should_proceed_true_when_only_warnings():
    res = PlausibilityResult(
        failures=[
            PlausibilityFailure(
                failure_type="F1_dose", severity="warning", reasoning="warn"
            ),
            PlausibilityFailure(
                failure_type="F2_feasibility", severity="warning", reasoning="warn"
            ),
        ]
    )
    assert res.should_proceed_to_pipeline is True


def test_should_proceed_false_when_any_blocking():
    res = PlausibilityResult(
        failures=[
            PlausibilityFailure(
                failure_type="F1_dose", severity="warning", reasoning="w"
            ),
            PlausibilityFailure(
                failure_type="F3_mechanism", severity="blocking", reasoning="b"
            ),
        ]
    )
    assert res.should_proceed_to_pipeline is False


def test_cannot_override_should_proceed_to_inconsistent_state():
    """Even if caller passes True, a blocking failure drives it to False."""
    res = PlausibilityResult(
        should_proceed_to_pipeline=True,
        failures=[
            PlausibilityFailure(
                failure_type="F3_mechanism", severity="blocking", reasoning="b"
            )
        ],
    )
    assert res.should_proceed_to_pipeline is False


def test_reasoning_summary_and_warnings_passthrough():
    res = PlausibilityResult(
        warnings=["w1"], reasoning_summary="all good"
    )
    assert res.warnings == ["w1"]
    assert res.reasoning_summary == "all good"
