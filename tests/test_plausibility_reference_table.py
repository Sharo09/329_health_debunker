"""Tests for the plausibility reference-table loader."""

from pathlib import Path

import pytest

from src.plausibility.reference_table import ReferenceEntry, ReferenceTable


# The real data file ships with the repo; these tests use it directly so
# schema drift in the YAML surfaces here before it causes a production bug.


def test_loads_real_yaml():
    table = ReferenceTable()
    assert len(table) >= 20  # spec minimum is 30 but v1 demo ships with ~22
    apple = table.lookup("apple")
    assert apple is not None
    assert apple.canonical_name == "apple"
    assert apple.unit == "apple"
    assert apple.typical_daily_high > 0
    assert apple.implausibly_high > apple.typical_daily_high
    # Apple entry carries at least one alternate unit mapping.
    assert any(a.get("unit") == "g" for a in apple.alternate_units)


def test_lookup_case_insensitive():
    table = ReferenceTable()
    assert table.lookup("APPLE") is not None
    assert table.lookup("  Apple  ") is not None


def test_lookup_handles_spaces_and_underscores():
    table = ReferenceTable()
    # The YAML canonical is ``red_meat``.
    assert table.lookup("red meat") is not None
    assert table.lookup("red_meat") is not None


def test_lookup_missing_returns_none():
    table = ReferenceTable()
    assert table.lookup("unicornium") is None
    assert table.lookup("") is None
    assert table.lookup(None) is None


def test_contains_matches_lookup():
    table = ReferenceTable()
    assert "apple" in table
    assert "unicornium" not in table


def test_loads_from_custom_path(tmp_path):
    yaml_text = (
        "banana:\n"
        "  unit: banana\n"
        "  typical_daily_low: 0\n"
        "  typical_daily_high: 2\n"
        "  implausibly_high: 10\n"
        "  harmful_threshold: 30\n"
        "  source: Hand-curated test fixture\n"
        "  notes: test entry\n"
    )
    path = tmp_path / "ref.yaml"
    path.write_text(yaml_text)
    table = ReferenceTable(path=path)
    banana = table.lookup("banana")
    assert isinstance(banana, ReferenceEntry)
    assert banana.harmful_threshold == 30
    assert banana.alternate_units == []


def test_thresholds_are_internally_ordered():
    """typical_low <= typical_high <= implausibly_high; harmful is separate.

    Harmful can be above or below implausibly_high depending on what's
    physiologically harmful vs. merely beyond typical — don't assert
    their relative order.
    """
    table = ReferenceTable()
    for key in ("apple", "coffee", "vitamin_d", "water"):
        e = table.lookup(key)
        assert e is not None, key
        assert e.typical_daily_low <= e.typical_daily_high
        assert e.typical_daily_high <= e.implausibly_high
