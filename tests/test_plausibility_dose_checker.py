"""Tests for the F1 dose-plausibility checker."""

import json
from pathlib import Path

import pytest

from src.plausibility.dose_checker import (
    check_dose_plausibility,
    normalize_to_reference_unit,
    parse_dose,
)
from src.plausibility.reference_table import ReferenceEntry, ReferenceTable
from src.plausibility.schemas import ParsedDose


# ---------- fixtures ----------


@pytest.fixture
def table(tmp_path) -> ReferenceTable:
    """A small hand-curated table so the checker tests are hermetic."""
    yaml_text = (
        "apple:\n"
        "  unit: apple\n"
        "  typical_daily_low: 0\n"
        "  typical_daily_high: 3\n"
        "  implausibly_high: 10\n"
        "  harmful_threshold: 20\n"
        "  source: test source\n"
        "  notes: test notes\n"
        "  alternate_units:\n"
        "    - unit: g\n"
        "      ratio: 0.00556\n"
        "vitamin_d:\n"
        "  unit: IU\n"
        "  typical_daily_low: 400\n"
        "  typical_daily_high: 2000\n"
        "  implausibly_high: 10000\n"
        "  harmful_threshold: 4000\n"
        "  source: test UL\n"
        "  notes: test vitamin D\n"
        "  alternate_units:\n"
        "    - unit: mcg\n"
        "      ratio: 40\n"
    )
    path = tmp_path / "ref.yaml"
    path.write_text(yaml_text)
    return ReferenceTable(path=path)


class _FakeLLM:
    """Returns a fixed ``ParsedDose`` and records inputs."""

    def __init__(self, parsed: ParsedDose | Exception):
        self._parsed = parsed
        self.calls: list[list[dict]] = []

    def extract(self, messages, response_schema):
        self.calls.append([dict(m) for m in messages])
        if isinstance(self._parsed, Exception):
            raise self._parsed
        return self._parsed


# ---------- parse_dose ----------


def test_parse_dose_empty_returns_none():
    llm = _FakeLLM(ParsedDose(raw_source=""))
    assert parse_dose("", "apple", llm) is None
    assert parse_dose(None, "apple", llm) is None
    assert parse_dose("   ", "apple", llm) is None
    assert llm.calls == []  # never reached the LLM


def test_parse_dose_happy_path():
    expected = ParsedDose(
        numeric_value=100,
        unit="apple",
        time_basis="per day",
        confidence="high",
        raw_source="100 apples per day",
    )
    llm = _FakeLLM(expected)
    out = parse_dose("100 apples per day", "apple", llm)
    assert out == expected
    assert len(llm.calls) == 1
    assert any("raw_dose: 100 apples per day" in m["content"] for m in llm.calls[0])


def test_parse_dose_llm_failure_returns_none():
    llm = _FakeLLM(RuntimeError("provider down"))
    assert parse_dose("anything", "apple", llm) is None


# ---------- normalize_to_reference_unit ----------


def test_normalize_exact_unit_match(table):
    entry = table.lookup("apple")
    parsed = ParsedDose(
        numeric_value=5, unit="apples", time_basis="per day",
        confidence="high", raw_source="5 apples/day",
    )
    assert normalize_to_reference_unit(parsed, entry) == 5


def test_normalize_alternate_unit_converts(table):
    entry = table.lookup("apple")
    parsed = ParsedDose(
        numeric_value=1800, unit="g", time_basis="per day",
        confidence="high", raw_source="1800g/day",
    )
    # 1800 * 0.00556 ≈ 10.008
    out = normalize_to_reference_unit(parsed, entry)
    assert out is not None
    assert out == pytest.approx(1800 * 0.00556)


def test_normalize_mcg_to_iu_vitamin_d(table):
    entry = table.lookup("vitamin_d")
    parsed = ParsedDose(
        numeric_value=100, unit="mcg", time_basis="per day",
        confidence="high", raw_source="100 mcg",
    )
    # 100 mcg * 40 IU/mcg = 4000 IU
    assert normalize_to_reference_unit(parsed, entry) == pytest.approx(4000)


def test_normalize_unknown_unit_returns_none(table):
    entry = table.lookup("apple")
    parsed = ParsedDose(
        numeric_value=5, unit="parsecs", time_basis="per day",
        confidence="high", raw_source="5 parsecs",
    )
    assert normalize_to_reference_unit(parsed, entry) is None


def test_normalize_numeric_only_assumes_ref_unit(table):
    """Bare number with no unit → interpret as the reference's own unit."""
    entry = table.lookup("apple")
    parsed = ParsedDose(
        numeric_value=7, unit=None, time_basis="per day",
        confidence="medium", raw_source="7/day",
    )
    assert normalize_to_reference_unit(parsed, entry) == 7


def test_normalize_numeric_none_returns_none(table):
    entry = table.lookup("apple")
    parsed = ParsedDose(
        numeric_value=None, unit="apple", confidence="low", raw_source="some",
    )
    assert normalize_to_reference_unit(parsed, entry) is None


# ---------- check_dose_plausibility ----------


def _parsed(value, unit="apple"):
    return ParsedDose(
        numeric_value=value, unit=unit, time_basis="per day",
        confidence="high", raw_source=f"{value} {unit}",
    )


def test_below_typical_is_fine(table):
    assert check_dose_plausibility("apple", _parsed(1), table) is None


def test_at_typical_is_fine(table):
    assert check_dose_plausibility("apple", _parsed(3), table) is None


def test_above_typical_below_implausible_is_fine(table):
    # 5 apples/day is above typical_daily_high=3 but below implausibly_high=10
    assert check_dose_plausibility("apple", _parsed(5), table) is None


def test_at_implausible_fires_warning(table):
    f = check_dose_plausibility("apple", _parsed(10), table)
    assert f is not None
    assert f.failure_type == "F1_dose"
    assert f.severity == "warning"
    assert "typical" in f.reasoning.lower() or "realistic" in f.reasoning.lower()
    assert f.supporting_data["stated_value"] == 10
    assert f.supporting_data["typical_range"] == [0, 3]


def test_at_harmful_fires_blocking(table):
    f = check_dose_plausibility("apple", _parsed(20), table)
    assert f is not None
    assert f.failure_type == "F1_dose"
    assert f.severity == "blocking"
    assert "harmful" in f.reasoning.lower()
    assert f.supporting_data["harmful_threshold"] == 20


def test_far_above_harmful_fires_blocking(table):
    f = check_dose_plausibility("apple", _parsed(100), table)
    assert f is not None
    assert f.severity == "blocking"


def test_missing_food_returns_none(table):
    assert check_dose_plausibility(None, _parsed(100), table) is None
    assert check_dose_plausibility("", _parsed(100), table) is None


def test_not_a_dose_returns_none(table):
    parsed = ParsedDose(
        numeric_value=None, unit=None, confidence="not_a_dose",
        raw_source="a lot",
    )
    assert check_dose_plausibility("apple", parsed, table) is None


def test_missing_parse_returns_none(table):
    assert check_dose_plausibility("apple", None, table) is None


def test_food_not_in_table_returns_none(table):
    assert check_dose_plausibility("kumquat", _parsed(1000), table) is None


def test_unit_mismatch_returns_none(table):
    parsed = ParsedDose(
        numeric_value=500, unit="liters", time_basis="per day",
        confidence="high", raw_source="500 liters",
    )
    assert check_dose_plausibility("apple", parsed, table) is None


def test_vitamin_d_harmful_via_alt_unit(table):
    # 150 mcg = 6000 IU, above harmful_threshold 4000
    parsed = ParsedDose(
        numeric_value=150, unit="mcg", time_basis="per day",
        confidence="high", raw_source="150 mcg",
    )
    f = check_dose_plausibility("vitamin_d", parsed, table)
    assert f is not None
    assert f.severity == "blocking"
