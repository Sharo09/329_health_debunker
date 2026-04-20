"""Tests for the deterministic stratum assigner (Patch B Task 4)."""

from __future__ import annotations

import pytest

from src.synthesis.stratum_assigner import (
    _canonical_form,
    _canonical_frequency,
    _classify_population,
    _parse_dose_to_numeric,
    assign_dose_stratum,
    assign_form_stratum,
    assign_frequency_stratum,
    assign_population_stratum,
)


# ---------------------------------------------------------------------------
# _parse_dose_to_numeric
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("500 mg", 500.0),
        ("500mg", 500.0),
        ("500 mg/day", 500.0),
        ("500 mg per day", 500.0),
        ("500 mg twice daily", 1000.0),
        ("500 mg three times daily", 1500.0),
        ("1000 IU", 1000.0),
        ("1000 IU (500 IU twice daily)", 1000.0),
        ("2-3 cups/day", 2.5),
        ("1-2 cups per day", 1.5),
        ("10 uM (in vitro concentration)", 10.0),
        ("4000 IU/day", 4000.0),
        ("2.5 g", 2.5),
        ("100 mg weekly", 100.0 / 7.0),
        ("3 per day", 3.0),
        ("5", 5.0),
    ],
)
def test_parse_dose_happy_path(raw, expected):
    got = _parse_dose_to_numeric(raw)
    assert got is not None
    assert got == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize(
    "raw",
    ["", None, "moderate", "a lot", "low", "some", "unknown"],
)
def test_parse_dose_returns_none_on_vague_input(raw):
    assert _parse_dose_to_numeric(raw) is None


# ---------------------------------------------------------------------------
# assign_dose_stratum — 20+ cases across thresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user,paper,expected",
    [
        # Identical doses → matches.
        ("500 mg/day", "500 mg/day", "matches"),
        ("1000 IU", "1000 IU", "matches"),
        # Within 0.5–2.0× ratio → matches.
        ("500 mg/day", "1000 mg/day", "matches"),  # 2.0× exactly
        ("500 mg/day", "250 mg/day", "matches"),   # 0.5× exactly
        ("500 mg/day", "750 mg/day", "matches"),
        ("500 mg/day", "400 mg/day", "matches"),
        # Just outside → higher / lower.
        ("500 mg/day", "1200 mg/day", "higher"),   # 2.4×
        ("500 mg/day", "200 mg/day", "lower"),     # 0.4×
        ("500 mg/day", "5000 mg/day", "higher"),   # 10×
        ("500 mg/day", "50 mg/day", "lower"),      # 0.1×
        # Twice-daily frequency math.
        ("500 mg twice daily", "500 mg twice daily", "matches"),  # 1000 vs 1000
        # Ratio 2.0 sits on the inclusive upper bound, so 500 vs 1000
        # (500 mg/day vs 500 mg twice daily) stays in "matches". Anything
        # strictly above 2.0 is "higher"; see next row.
        ("500 mg/day", "500 mg twice daily", "matches"),
        ("500 mg/day", "600 mg twice daily", "higher"),  # 500 vs 1200 = 2.4×
        # 100 IU vs 10000 IU — way higher.
        ("100 IU", "10000 IU", "higher"),
        # Range midpoints — user's 2-3 midpoint is 2.5.
        ("2-3 cups/day", "2 cups/day", "matches"),
        ("2-3 cups/day", "6 cups/day", "higher"),          # 2.4× above midpoint
        ("2-3 cups/day", "1 cup/day", "lower"),            # 0.4× of midpoint
        # Missing sides.
        (None, "500 mg/day", "not_applicable"),
        ("500 mg/day", None, "unreported"),
        (None, None, "not_applicable"),
        # Unparseable dose on either side.
        ("moderate", "500 mg/day", "not_applicable"),
        ("500 mg/day", "moderate", "unreported"),
    ],
)
def test_assign_dose(user, paper, expected):
    assert assign_dose_stratum(user, paper) == expected


def test_assign_dose_zero_user_falls_back_to_unreported():
    # Division by zero would happen if we weren't guarding — defensive.
    assert assign_dose_stratum("0 mg", "100 mg") == "unreported"


# ---------------------------------------------------------------------------
# _canonical_form + assign_form_stratum — 30+ phrasings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        # dietary
        ("dietary", "dietary"),
        ("Dietary", "dietary"),
        ("food", "dietary"),
        ("whole food", "dietary"),
        ("from food", "dietary"),
        ("from diet", "dietary"),
        ("diet", "dietary"),
        ("spice", "dietary"),
        ("culinary", "dietary"),
        ("whole-food", "dietary"),
        ("dietary intake", "dietary"),
        ("ingested food", "dietary"),
        # supplement
        ("supplement", "supplement"),
        ("Supplements", "supplement"),
        ("supplementation", "supplement"),
        ("pill", "supplement"),
        ("capsule", "supplement"),
        ("tablet", "supplement"),
        ("d3 supplement", "supplement"),
        ("d3 supplement", "supplement"),
        ("oral supplement", "supplement"),
        # extract
        ("extract", "extract"),
        ("standardized extract", "extract"),
        ("standardised extract", "extract"),
        ("concentrated extract", "extract"),
        # "dietary concentrated" is the turmeric-tea / golden-milk tier —
        # still a dietary form, just denser than raw spice.
        ("dietary concentrated", "dietary"),
        # isolated compound
        ("isolated", "isolated_compound"),
        ("pure compound", "isolated_compound"),
        ("isolated compound", "isolated_compound"),
        ("purified", "isolated_compound"),
        ("synthetic", "isolated_compound"),
        # topical
        ("topical", "topical"),
        ("cream", "topical"),
        ("ointment", "topical"),
        ("gel", "topical"),
        # fall-through (food-specific tokens stay as-is after normalisation)
        ("processed", "processed"),
        ("unprocessed", "unprocessed"),
        ("whole", "whole"),
        ("low fat", "low fat"),
        ("raw", "raw"),
    ],
)
def test_canonical_form(raw, expected):
    assert _canonical_form(raw) == expected


@pytest.mark.parametrize(
    "user,paper,expected",
    [
        # Canonical match cross-phrasing.
        ("dietary", "food", "matches"),
        ("dietary", "whole food", "matches"),
        ("supplement", "capsule", "matches"),
        ("supplement", "pill", "matches"),
        ("supplement", "d3 supplement", "matches"),
        ("extract", "standardized extract", "matches"),
        # Different canonical tokens.
        ("dietary", "supplement", "different"),
        ("dietary", "extract", "different"),
        ("supplement", "topical", "different"),
        ("extract", "isolated_compound", "different"),
        # Food-specific tokens via fallback.
        ("processed", "processed", "matches"),
        ("processed", "unprocessed", "different"),
        ("whole", "low fat", "different"),
        # Missing sides.
        (None, "dietary", "not_applicable"),
        ("dietary", None, "unreported"),
    ],
)
def test_assign_form(user, paper, expected):
    assert assign_form_stratum(user, paper) == expected


# ---------------------------------------------------------------------------
# Frequency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("daily", "daily"),
        ("every day", "daily"),
        ("once daily", "daily"),
        ("per day", "daily"),
        ("weekly", "weekly"),
        ("per week", "weekly"),
        ("twice daily", "multi daily"),
        ("multiple times per day", "multi daily"),
        ("occasional", "occasional"),
        ("rarely", "occasional"),
        ("5:2", "five two"),
        ("alternate day", "alternate day"),
    ],
)
def test_canonical_frequency(raw, expected):
    assert _canonical_frequency(raw) == expected


@pytest.mark.parametrize(
    "user,paper,expected",
    [
        ("daily", "daily", "matches"),
        ("daily", "once daily", "matches"),
        ("daily", "weekly", "different"),
        ("weekly", "weekly", "matches"),
        ("occasional", "occasional", "matches"),
        ("daily", "occasional", "different"),
        (None, "daily", "not_applicable"),
        ("daily", None, "unreported"),
    ],
)
def test_assign_frequency(user, paper, expected):
    assert assign_frequency_stratum(user, paper) == expected


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------


def test_classify_population_picks_up_adult_bracket():
    brackets, conds = _classify_population("healthy adults aged 20-45")
    assert "adult" in brackets
    assert conds == set()


def test_classify_population_picks_up_pregnancy():
    _, conds = _classify_population("pregnant women")
    assert "pregnant" in conds


def test_classify_population_picks_up_disease():
    _, conds = _classify_population("adults with knee osteoarthritis")
    assert "inflammatory" in conds


def test_classify_population_empty():
    assert _classify_population("") == (set(), set())
    assert _classify_population(None) == (set(), set())


@pytest.mark.parametrize(
    "user,paper,expected",
    [
        # Same age bracket, no conditions → matches.
        ("healthy adults", "general adult population", "matches"),
        ("adults", "adults aged 20-45", "matches"),
        # Different age brackets → different.
        ("children", "adults", "different"),
        ("infants", "adults", "different"),
        ("adults", "older adults", "different"),
        # Pregnancy asymmetry → different.
        ("pregnant women", "adults", "different"),
        ("adults", "pregnant women", "different"),
        ("pregnant women", "pregnant adults", "matches"),
        # Disease-matched populations.
        ("adults with type 2 diabetes", "T2D patients", "matches"),
        ("adults with arthritis", "adults with knee osteoarthritis", "matches"),
        # Healthy user vs diseased paper → different.
        ("healthy adults", "adults with knee osteoarthritis", "different"),
        # Condition mismatch between two diseased populations.
        ("adults with arthritis", "adults with diabetes", "different"),
        # In-vitro / animal populations mismatch human users.
        ("healthy adults", "HeLa cell line (in vitro)", "different"),
        ("healthy adults", "mice", "different"),
        # Missing sides.
        (None, "adults", "not_applicable"),
        ("adults", None, "unreported"),
    ],
)
def test_assign_population(user, paper, expected):
    assert assign_population_stratum(user, paper) == expected


def test_assign_population_unclassifiable_paper_returns_unreported():
    # Paper text that yields no age bracket and no condition flag.
    assert assign_population_stratum("adults", "n=80") == "unreported"
