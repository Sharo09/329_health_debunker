"""Deterministic stratum assignment — Task 4 of elicitation Patch B.

Compares the user's stated value for a stratifier slot to a paper's
studied value (both from free-text sources) and classifies the
relationship into one of the ``StratumMatch`` buckets.

Why deterministic?

- Stratum assignment must be auditable. An LLM "matches" decision is
  hard to debug weeks later; a ratio comparison is obvious.
- Running 40 papers × 4 slots through another LLM call would add
  latency we can't afford.

The trade-off is that the assigner ships with hand-curated token
tables for ``form`` and ``population``. When a paper uses a phrasing
the tables don't cover, the assigner returns ``unreported`` — the
fail-open default, consistent with the rest of Patch B.
"""

from __future__ import annotations

import re
from typing import Optional

from src.synthesis.schemas import StratumMatch

# ---------------------------------------------------------------------------
# Dose
# ---------------------------------------------------------------------------
#
# Ratio thresholds come from the spec: 0.5 <= paper/user <= 2.0 is
# "matches", else "higher" / "lower". Thresholds are on the ratio, not
# on absolute dose, so they generalise across substances.

_DOSE_MATCH_LOW = 0.5
_DOSE_MATCH_HIGH = 2.0

# Multipliers for frequency modifiers that scale a per-unit dose into
# per-day. "500 mg twice daily" -> 1000; "500 mg once weekly" -> 500/7.
_FREQ_MULTIPLIERS: dict[str, float] = {
    "once daily": 1.0,
    "daily": 1.0,
    "per day": 1.0,
    "/day": 1.0,
    "twice daily": 2.0,
    "two times daily": 2.0,
    "2x daily": 2.0,
    "three times daily": 3.0,
    "3x daily": 3.0,
    "four times daily": 4.0,
    "weekly": 1.0 / 7.0,
    "per week": 1.0 / 7.0,
    "/week": 1.0 / 7.0,
}


def _parse_dose_to_numeric(raw: Optional[str]) -> Optional[float]:
    """Pull a numeric per-day amount from dose text.

    Handles a few common shapes:

    - ``"500 mg"`` → 500
    - ``"500 mg twice daily"`` → 1000
    - ``"2-3 cups/day"`` → 2.5 (range midpoint)
    - ``"10 uM (in vitro concentration)"`` → 10
    - ``"1000 IU (500 IU twice daily)"`` → 1000 (first number wins when
      a summary is followed by a per-dose breakdown in parens)
    - vague English like ``"moderate"``, ``"a lot"`` → ``None``

    Returns ``None`` whenever no number can be recovered. Callers treat
    ``None`` on either side as "skip this stratum" rather than guessing.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None

    # Pull the first numeric run — optionally a range like "2-3".
    range_m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", s)
    if range_m:
        lo = float(range_m.group(1))
        hi = float(range_m.group(2))
        base = (lo + hi) / 2.0
    else:
        num_m = re.search(r"(\d+(?:\.\d+)?)", s)
        if not num_m:
            return None
        base = float(num_m.group(1))

    # Scale by a frequency modifier if one appears in the text (e.g.
    # "500 mg twice daily" -> multiply by 2). Parentheticals like
    # "(500 mg twice daily)" are ignored because the number we already
    # pulled is the higher-level summary.
    outside_paren = re.sub(r"\([^)]*\)", "", s).strip()
    for phrase, factor in _FREQ_MULTIPLIERS.items():
        if phrase in outside_paren and factor != 1.0:
            base *= factor
            break

    return base


def assign_dose_stratum(
    user_value: Optional[str],
    paper_value: Optional[str],
) -> StratumMatch:
    """Compare user's stated dose to paper's studied dose.

    Ratio ``paper/user`` in ``[0.5, 2.0]`` → matches, above → higher,
    below → lower. Either side unparseable → ``unreported`` (paper side)
    or ``not_applicable`` (user side).
    """
    if user_value is None:
        return "not_applicable"
    if paper_value is None:
        return "unreported"

    user_num = _parse_dose_to_numeric(user_value)
    paper_num = _parse_dose_to_numeric(paper_value)
    if user_num is None:
        return "not_applicable"
    if paper_num is None or user_num == 0:
        return "unreported"

    ratio = paper_num / user_num
    if _DOSE_MATCH_LOW <= ratio <= _DOSE_MATCH_HIGH:
        return "matches"
    return "higher" if ratio > _DOSE_MATCH_HIGH else "lower"


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

# Canonical token table — hand-curated mappings from common English
# phrasings to a small closed set. The spec calls this out as
# load-bearing: bad normalisation here undermines every downstream
# stratum, so we keep it explicit and grow it as eval cases surface
# gaps.
_FORM_CANONICAL: dict[str, list[str]] = {
    "dietary": [
        "dietary", "food", "whole food", "from food", "from diet",
        "diet", "spice", "culinary", "as food", "foods", "whole-food",
        "ingested food", "dietary intake",
    ],
    "supplement": [
        "supplement", "supplements", "supplementation", "pill",
        "capsule", "tablet", "d3 supplement", "d2 supplement",
        "supplemental", "oral supplement", "supplemented",
    ],
    "extract": [
        "extract", "extracts", "standardized extract", "standardised extract",
        "concentrated extract", "concentrated",
        "standardized", "standardised",
    ],
    "isolated_compound": [
        "isolated", "pure compound", "isolated compound", "purified",
        "synthetic", "pure", "chemical",
    ],
    "topical": [
        "topical", "cream", "ointment", "gel", "patch", "lotion",
    ],
}


def _canonical_form(raw: Optional[str]) -> Optional[str]:
    """Normalise a free-text form to one of the canonical tokens.

    Falls back to the stripped-lowercase value when no mapping hits —
    that way the caller can still compare food-specific tokens like
    ``"processed"`` vs ``"unprocessed"`` via direct equality.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    # Normalise separators and common noise.
    norm = s.replace("-", " ").replace("_", " ").strip()
    for canonical, phrasings in _FORM_CANONICAL.items():
        for phrasing in phrasings:
            if phrasing == norm:
                return canonical
            # Substring match for phrases like "curcumin supplement" or
            # "dietary turmeric consumption".
            if re.search(rf"\b{re.escape(phrasing)}\b", norm):
                return canonical
    # No canonical hit — return the normalised raw token. Callers that
    # compare food-specific form tokens (e.g. "processed") rely on this.
    return norm


def assign_form_stratum(
    user_value: Optional[str],
    paper_value: Optional[str],
) -> StratumMatch:
    """Compare user form to paper form via canonical tokens.

    Returns ``matches`` when both canonicalise to the same token,
    ``different`` when both are known but distinct, and ``unreported`` /
    ``not_applicable`` as appropriate for missing sides.
    """
    if user_value is None:
        return "not_applicable"
    if paper_value is None:
        return "unreported"

    u = _canonical_form(user_value)
    p = _canonical_form(paper_value)
    if not u:
        return "not_applicable"
    if not p:
        return "unreported"
    return "matches" if u == p else "different"


# ---------------------------------------------------------------------------
# Frequency
# ---------------------------------------------------------------------------

_FREQUENCY_CANONICAL: dict[str, list[str]] = {
    "multi_daily": ["multiple times per day", "multi daily", "several times a day", "twice daily", "3x daily"],
    "daily": ["daily", "every day", "per day", "once a day", "once daily", "each day"],
    "weekly": ["weekly", "per week", "once a week", "each week"],
    "occasional": ["occasional", "occasionally", "sporadic", "rarely", "less than weekly", "rare"],
    "time_restricted_16_8": ["16:8", "time-restricted", "time restricted eating"],
    "five_two": ["5:2"],
    "alternate_day": ["alternate day", "alternate-day", "every other day"],
    "extended": ["extended", "prolonged", "multi-day fast"],
}


def _canonical_frequency(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower().replace("_", " ").replace("-", " ")
    if not s:
        return None
    for canonical, phrasings in _FREQUENCY_CANONICAL.items():
        for phrasing in phrasings:
            if phrasing == s or re.search(rf"\b{re.escape(phrasing)}\b", s):
                return canonical
    return s


def assign_frequency_stratum(
    user_value: Optional[str],
    paper_value: Optional[str],
) -> StratumMatch:
    if user_value is None:
        return "not_applicable"
    if paper_value is None:
        return "unreported"
    u = _canonical_frequency(user_value)
    p = _canonical_frequency(paper_value)
    if not u:
        return "not_applicable"
    if not p:
        return "unreported"
    return "matches" if u == p else "different"


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------
#
# Populations are classified into (age_bracket, condition_flags). Two
# populations "match" when their age brackets overlap AND their
# condition-flag sets agree (exact equality on conditions, because a
# paper studying arthritis patients doesn't transfer cleanly to healthy
# users, and vice versa).

# Ordered most-specific → most-generic: "older adults" contains the
# word "adults", so older_adult has to be probed before adult or the
# generic bucket would swallow the more-specific one. Infant / child /
# adolescent are disjoint from adult, so their order doesn't matter —
# they're listed before adult just for readability.
_AGE_BRACKETS: dict[str, list[str]] = {
    "older_adult": ["older adult", "older adults", "elderly", "senior", "seniors", "geriatric", "aged 65", "65+", "over 65", "aged over 65"],
    "infant": ["infant", "infants", "baby", "babies", "newborn", "newborns", "neonate", "neonates"],
    "child": ["child", "children", "kids", "paediatric", "pediatric", "school age", "school-age"],
    "adolescent": ["adolescent", "adolescents", "teen", "teenager", "teenagers", "youth"],
    "adult": ["adult", "adults", "men", "women", "healthy adults", "healthy adult", "general adult", "general adults", "middle aged", "middle-aged"],
}

_CONDITION_FLAGS: dict[str, list[str]] = {
    "pregnant": ["pregnant", "pregnancy", "gestational", "lactating", "breastfeeding", "postpartum"],
    "diabetic": ["diabetic", "diabetes", "t2d", "type 2 diabetes", "type-2 diabetes", "insulin resistant", "insulin resistance", "prediabetic"],
    "cardiovascular": ["cardiovascular", "heart disease", "hypertension", "hypertensive", "cvd", "coronary"],
    "inflammatory": ["inflammatory", "arthritis", "osteoarthritis", "rheumatoid", "autoimmune"],
    "hypercholesterolemic": ["hypercholesterolemia", "high cholesterol", "hypercholesterolemic"],
    "liver": ["liver disease", "hepatic", "cirrhosis", "nafld", "fatty liver"],
    "obese": ["obese", "obesity", "overweight"],
    "cancer": ["cancer", "oncology", "tumor", "tumour", "malignancy", "carcinoma"],
    "deficient": ["deficient", "deficiency", "vitamin d deficient"],
    "in_vitro": ["in vitro", "cell line", "hela", "cells", "cell culture"],
    "animal": ["mouse", "mice", "rat", "rats", "rodent", "canine", "murine"],
}


def _classify_population(raw: Optional[str]) -> tuple[set[str], set[str]]:
    """Return (age_brackets, conditions) sets for a free-text population.

    Empty sets are legal — the comparison logic treats an empty
    age-bracket set as "unspecified", which overlaps with any bracket.
    Empty conditions means "no narrowing condition claimed."
    """
    if raw is None:
        return set(), set()
    s = str(raw).strip().lower().replace("_", " ").replace("-", " ")
    if not s:
        return set(), set()

    brackets: set[str] = set()
    # Walk in specificity order (see _AGE_BRACKETS comment). Once we
    # find a bracket, stop — "older adults" must not also match "adult"
    # via its substring word.
    for bracket, phrasings in _AGE_BRACKETS.items():
        for phrasing in phrasings:
            if re.search(rf"\b{re.escape(phrasing)}\b", s):
                brackets.add(bracket)
                break
        if brackets:
            break

    conditions: set[str] = set()
    for flag, phrasings in _CONDITION_FLAGS.items():
        for phrasing in phrasings:
            if re.search(rf"\b{re.escape(phrasing)}\b", s):
                conditions.add(flag)
                break

    # Exception: "healthy" cancels the "no narrowing condition" default
    # without adding a condition — but also explicitly blocks matching
    # a diseased population. We model this by NOT adding a flag; the
    # condition-set equality check is what actually separates healthy
    # from diseased populations.
    return brackets, conditions


def assign_population_stratum(
    user_value: Optional[str],
    paper_value: Optional[str],
) -> StratumMatch:
    """Compare user's population to paper's studied population.

    Matches when age brackets overlap (or at least one is unspecified)
    AND condition-flag sets are equal. Anything else → different.
    """
    if user_value is None:
        return "not_applicable"
    if paper_value is None:
        return "unreported"

    u_brackets, u_conditions = _classify_population(user_value)
    p_brackets, p_conditions = _classify_population(paper_value)

    # If neither side extracts any signal, we can't say matches — treat
    # the paper as unreported for this slot.
    if not u_brackets and not u_conditions:
        return "not_applicable"
    if not p_brackets and not p_conditions:
        return "unreported"

    # Age: unspecified on either side is permissive; otherwise overlap.
    if u_brackets and p_brackets and not (u_brackets & p_brackets):
        return "different"

    # Conditions: exact set equality. A paper on "arthritis patients"
    # doesn't stand in for a question about "healthy adults", and
    # vice versa.
    if u_conditions != p_conditions:
        return "different"

    return "matches"


__all__ = [
    "assign_dose_stratum",
    "assign_form_stratum",
    "assign_frequency_stratum",
    "assign_population_stratum",
]
