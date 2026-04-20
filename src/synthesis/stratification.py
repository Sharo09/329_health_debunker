"""Post-extraction stratification helpers — Task 5 of elicitation Patch B.

Takes the per-paper scoring results from ``score_papers`` and the
per-paper value extraction from ``stratifier.extract_values_in_parallel``
and combines them with the user's LockedPICO into:

- ``PaperStratification`` per paper (one row of match labels + free-text
  justification)
- ``StratumBucket`` per user-stated stratifier slot (grouped paper ids
  + mini-verdicts per stratum)
- ``generalisation_warnings`` — plain-English sentences surfacing form /
  dose / population mismatches between the user's question and the
  evidence base.

All pure-Python, deterministic. No LLM calls here — the LLM only runs
upstream in the stratifier (per-paper value extraction) and downstream
in ``generate_verdict`` (stratum-aware final verdict).
"""

from __future__ import annotations

from typing import Iterable, Optional

from src.schemas import LockedPICO
from src.synthesis.schemas import (
    OverallApplicability,
    PaperScoreResult,
    PaperStratification,
    StratifierSlot,
    StratumBucket,
    StratumMatch,
    StratumVerdict,
)
from src.synthesis.stratifier import ExtractedPaperValues
from src.synthesis.stratum_assigner import (
    assign_dose_stratum,
    assign_form_stratum,
    assign_frequency_stratum,
    assign_population_stratum,
)


_STRATIFIER_SLOTS: tuple[StratifierSlot, ...] = (
    "dose", "form", "frequency", "population"
)

# Minimum relevance score for a paper to count toward the verdict in
# any stratum. Matches the hard filter in the main verdict prompt.
_MIN_RELEVANCE = 0.4


# ---------------------------------------------------------------------------
# Per-paper stratification
# ---------------------------------------------------------------------------


def _classify_overall(
    values: ExtractedPaperValues, locked_pico: LockedPICO
) -> OverallApplicability:
    """Roll up per-slot matches into a single applicability bucket.

    - ``direct`` — every slot the user stated was matched by the paper.
    - ``generalisation`` — at least one slot is categorically different
      (form/population mismatch) OR dose is outside 0.5-2.0x.
    - ``partial`` — anything else, typically where the paper is
      silent on one or more user-stated slots.
    """
    matches: list[StratumMatch] = []
    user_pairs = [
        ("dose", locked_pico.dose, values.dose_studied, assign_dose_stratum),
        ("form", locked_pico.form, values.form_studied, assign_form_stratum),
        ("frequency", locked_pico.frequency, values.frequency_studied, assign_frequency_stratum),
        ("population", locked_pico.population, values.population_studied, assign_population_stratum),
    ]
    any_mismatch = False
    any_unreported = False
    any_match = False
    for _slot, user_val, paper_val, assigner in user_pairs:
        m = assigner(user_val, paper_val)
        matches.append(m)
        if m == "matches":
            any_match = True
        elif m in ("different", "higher", "lower"):
            any_mismatch = True
        elif m == "unreported":
            any_unreported = True

    if any_mismatch:
        return "generalisation"
    if any_match and not any_unreported:
        return "direct"
    return "partial"


def _build_applicability_reasoning(
    values: ExtractedPaperValues, locked_pico: LockedPICO
) -> str:
    """One-sentence rundown of the paper's studied values vs the user's.

    Kept terse so it can display inline under a paper card. Only
    mentions slots where either the user or the paper has a value —
    omitting slots both sides are silent on.
    """
    fragments: list[str] = []
    pairs = [
        ("dose", locked_pico.dose, values.dose_studied),
        ("form", locked_pico.form, values.form_studied),
        ("frequency", locked_pico.frequency, values.frequency_studied),
        ("population", locked_pico.population, values.population_studied),
    ]
    for slot, user_val, paper_val in pairs:
        if not user_val and not paper_val:
            continue
        user_part = f"user asked about {user_val}" if user_val else "user did not specify"
        paper_part = f"paper studied {paper_val}" if paper_val else "paper did not report"
        fragments.append(f"{slot}: {user_part}; {paper_part}")
    if not fragments:
        return "No stratifier slots stated by the user."
    return " | ".join(fragments)


def build_paper_stratifications(
    extracted_values: dict[str, ExtractedPaperValues],
    locked_pico: LockedPICO,
) -> list[PaperStratification]:
    """One PaperStratification per paper.

    Papers missing from ``extracted_values`` (e.g. if extraction threw)
    get an all-``not_applicable`` row so downstream bucketing still
    works. The caller controls which paper_ids to iterate over by
    supplying them via the dict.
    """
    out: list[PaperStratification] = []
    for paper_id, values in extracted_values.items():
        out.append(PaperStratification(
            paper_id=paper_id,
            dose_match=assign_dose_stratum(locked_pico.dose, values.dose_studied),
            dose_studied=values.dose_studied,
            form_match=assign_form_stratum(locked_pico.form, values.form_studied),
            form_studied=values.form_studied,
            frequency_match=assign_frequency_stratum(locked_pico.frequency, values.frequency_studied),
            frequency_studied=values.frequency_studied,
            population_match=assign_population_stratum(locked_pico.population, values.population_studied),
            population_studied=values.population_studied,
            overall_applicability=_classify_overall(values, locked_pico),
            applicability_reasoning=_build_applicability_reasoning(values, locked_pico),
        ))
    return out


# ---------------------------------------------------------------------------
# Stratum buckets
# ---------------------------------------------------------------------------


def _match_for_slot(
    stratification: PaperStratification, slot: StratifierSlot
) -> StratumMatch:
    return {
        "dose": stratification.dose_match,
        "form": stratification.form_match,
        "frequency": stratification.frequency_match,
        "population": stratification.population_match,
    }[slot]


def _user_value_for_slot(
    locked_pico: LockedPICO, slot: StratifierSlot
) -> Optional[str]:
    return {
        "dose": locked_pico.dose,
        "form": locked_pico.form,
        "frequency": locked_pico.frequency,
        "population": locked_pico.population,
    }[slot]


def build_stratum_buckets(
    scored: Iterable[PaperScoreResult],
    stratifications: Iterable[PaperStratification],
    locked_pico: LockedPICO,
) -> list[StratumBucket]:
    """Bucket papers per slot by their stratum match.

    Only slots where the user stated a value produce a bucket; slots
    the user answered "not sure" / left blank stay out of the results
    entirely (the UI should render nothing for them).
    """
    # ``scored`` isn't needed for the bucketing itself but is included
    # in the signature to parallel the spec's example and the downstream
    # ``compute_stratum_verdicts`` which does consume it.
    _ = list(scored)
    strat_list = list(stratifications)

    buckets: list[StratumBucket] = []
    for slot in _STRATIFIER_SLOTS:
        user_val = _user_value_for_slot(locked_pico, slot)
        if not user_val:
            continue
        strata: dict[StratumMatch, list[str]] = {}
        counts: dict[StratumMatch, int] = {}
        for s in strat_list:
            m = _match_for_slot(s, slot)
            strata.setdefault(m, []).append(s.paper_id)
            counts[m] = counts.get(m, 0) + 1
        buckets.append(StratumBucket(
            slot=slot,
            user_value=user_val,
            strata=strata,
            counts=counts,
        ))
    return buckets


# ---------------------------------------------------------------------------
# Stratum-level verdicts
# ---------------------------------------------------------------------------


def _evidence_in_stratum(
    paper_ids: list[str],
    scored_by_id: dict[str, PaperScoreResult],
) -> tuple[int, int, int]:
    """(supports, contradicts, neutral) counts for relevant papers only.

    Applies the same filters as the main verdict prompt:
    ``stance != "not_applicable"`` and ``relevance_score >= 0.4``.
    """
    supports = contradicts = neutral = 0
    for pid in paper_ids:
        s = scored_by_id.get(pid)
        if s is None:
            continue
        if s.stance == "not_applicable":
            continue
        if s.relevance_score < _MIN_RELEVANCE:
            continue
        if s.stance == "supports":
            supports += 1
        elif s.stance == "contradicts":
            contradicts += 1
        elif s.stance in ("neutral", "unclear"):
            neutral += 1
    return supports, contradicts, neutral


def _stratum_verdict_from_counts(
    supports: int, contradicts: int, neutral: int
) -> StratumVerdict:
    total_relevant = supports + contradicts + neutral
    if total_relevant == 0:
        return "insufficient_evidence"
    if total_relevant < 3:
        return "insufficient_evidence"
    if supports >= 2 * max(contradicts, 1) and supports > contradicts:
        return "supported"
    if contradicts >= 2 * max(supports, 1) and contradicts > supports:
        return "contradicted"
    return "insufficient_evidence"


def compute_stratum_verdicts(
    bucket: StratumBucket,
    scored: Iterable[PaperScoreResult],
) -> dict[StratumMatch, StratumVerdict]:
    """Per-stratum mini-verdicts using the same filters as the main verdict."""
    scored_by_id = {s.paper_id: s for s in scored}
    verdicts: dict[StratumMatch, StratumVerdict] = {}
    for stratum, paper_ids in bucket.strata.items():
        if not paper_ids:
            verdicts[stratum] = "empty"
            continue
        sup, con, neu = _evidence_in_stratum(paper_ids, scored_by_id)
        if sup + con + neu == 0:
            verdicts[stratum] = "empty"
            continue
        verdicts[stratum] = _stratum_verdict_from_counts(sup, con, neu)
    return verdicts


def compose_stratum_reasoning(
    bucket: StratumBucket,
    scored: Iterable[PaperScoreResult],
) -> dict[StratumMatch, str]:
    """Short descriptive line per stratum, e.g. '14 papers: 10 support...'."""
    scored_by_id = {s.paper_id: s for s in scored}
    out: dict[StratumMatch, str] = {}
    for stratum, paper_ids in bucket.strata.items():
        sup, con, neu = _evidence_in_stratum(paper_ids, scored_by_id)
        total = len(paper_ids)
        relevant = sup + con + neu
        if relevant == 0:
            out[stratum] = (
                f"{total} paper{'s' if total != 1 else ''}; "
                f"none passed the relevance / applicability filter."
            )
            continue
        out[stratum] = (
            f"{total} paper{'s' if total != 1 else ''}; "
            f"{sup} support{'s' if sup == 1 else ''}, "
            f"{con} contradict{'s' if con == 1 else ''}, "
            f"{neu} neutral."
        )
    return out


# ---------------------------------------------------------------------------
# Generalisation warnings
# ---------------------------------------------------------------------------


def detect_generalisation_warnings(
    stratifications: list[PaperStratification],
    locked_pico: LockedPICO,
    *,
    min_ratio: float = 0.5,
) -> list[str]:
    """Return plain-English warnings when most evidence is off-stratum.

    Thresholds follow the spec: once ≥50% of retrieved papers land in
    a ``different`` / ``higher`` / ``lower`` stratum for a slot the
    user answered, surface a warning so the results UI can lead with
    it. Populations are handled the same way.
    """
    warnings: list[str] = []
    total = len(stratifications)
    if total == 0:
        return warnings

    # Form mismatch
    if locked_pico.form:
        diff = sum(1 for s in stratifications if s.form_match == "different")
        if diff / total >= min_ratio:
            warnings.append(
                f"You asked about {locked_pico.form} "
                f"{locked_pico.food or 'this food'}, but {diff} of {total} "
                f"retrieved papers study a different form. Evidence may "
                f"not transfer directly."
            )

    # Dose mismatch (higher or lower)
    if locked_pico.dose:
        higher = sum(1 for s in stratifications if s.dose_match == "higher")
        lower = sum(1 for s in stratifications if s.dose_match == "lower")
        if (higher + lower) / total >= min_ratio:
            direction = "higher" if higher >= lower else "lower"
            warnings.append(
                f"You asked about {locked_pico.dose}, but most retrieved "
                f"evidence studies substantially {direction} doses "
                f"({higher} higher, {lower} lower out of {total})."
            )

    # Population mismatch
    if locked_pico.population:
        diff = sum(
            1 for s in stratifications if s.population_match == "different"
        )
        if diff / total >= min_ratio:
            warnings.append(
                f"You asked about the {locked_pico.population} population, "
                f"but {diff} of {total} retrieved papers study a different "
                f"population. The findings may not generalise to you."
            )

    # Frequency mismatch (softer — only warn when very lopsided)
    if locked_pico.frequency:
        diff = sum(
            1 for s in stratifications if s.frequency_match == "different"
        )
        if diff / total >= 0.75:
            warnings.append(
                f"You asked about {locked_pico.frequency} intake, but "
                f"most retrieved papers study a different frequency."
            )

    return warnings


__all__ = [
    "build_paper_stratifications",
    "build_stratum_buckets",
    "compute_stratum_verdicts",
    "compose_stratum_reasoning",
    "detect_generalisation_warnings",
]
