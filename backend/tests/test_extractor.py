"""Tests for ClaimExtractor (Task 6)."""

import json

import pytest

from backend.src.extraction.errors import EmptyClaimError
from backend.src.extraction.extractor import ClaimExtractor
from backend.src.extraction.llm_client import LLMClient
from backend.src.extraction.schemas import PartialPICO
from backend.tests.fixtures import (
    EXTRACTION_TEST_CASES,
    ExtractionTestCase,
    _absent_slot,
    _explicit,
    _make_pico_dict,
    mock_llm_provider,
)


def _build_extractor(
    pico_response: dict,
    tmp_path,
    *,
    provider_responses: list[str] | None = None,
) -> ClaimExtractor:
    """Build a ClaimExtractor whose LLMClient returns ``pico_response``.

    If ``provider_responses`` is set, use it directly (for retry tests).
    """
    if provider_responses is not None:
        pending = list(provider_responses)

        def provider(messages, response_schema, model, temperature):
            if not pending:
                raise AssertionError("provider ran out")
            return pending.pop(0)
    else:
        provider = mock_llm_provider(pico_response)

    client = LLMClient(
        provider=provider,
        log_file=str(tmp_path / "llm.jsonl"),
    )
    return ClaimExtractor(client, log_file=str(tmp_path / "ext.jsonl"))


# ---------- parametrized fixtures ----------

@pytest.mark.parametrize(
    "case",
    EXTRACTION_TEST_CASES,
    ids=[c.name for c in EXTRACTION_TEST_CASES],
)
def test_extraction_test_cases(case: ExtractionTestCase, tmp_path):
    extractor = _build_extractor(case.llm_mock_response, tmp_path)
    pico = extractor.extract(case.claim)

    assert isinstance(pico, PartialPICO)
    assert pico.is_food_claim is case.expected_is_food_claim

    if case.expected_food is None:
        assert pico.food.value is None
    else:
        assert pico.food.value == case.expected_food, (
            f"{case.name}: expected food={case.expected_food!r}, got {pico.food.value!r}"
        )

    if case.expected_outcome_present:
        assert pico.outcome.value is not None, (
            f"{case.name}: expected outcome to be present"
        )
    else:
        # Either absent or a vague value flagged as ambiguous.
        assert pico.outcome.value is None or "outcome" in pico.ambiguous_slots

    # Subset check on ambiguous_slots.
    missing = case.expected_ambiguous_slots - set(pico.ambiguous_slots)
    assert not missing, (
        f"{case.name}: missing expected ambiguous slots {missing} "
        f"(got {pico.ambiguous_slots})"
    )


# ---------- guard rails ----------

def test_empty_claim_raises(tmp_path):
    extractor = _build_extractor({}, tmp_path)
    with pytest.raises(EmptyClaimError):
        extractor.extract("")


def test_whitespace_only_claim_raises(tmp_path):
    extractor = _build_extractor({}, tmp_path)
    with pytest.raises(EmptyClaimError):
        extractor.extract("   \t\n  ")


def test_long_claim_is_truncated(tmp_path):
    long_claim = "Is " + ("very " * 200) + "coffee bad?"
    assert len(long_claim) > ClaimExtractor.MAX_CLAIM_LEN

    # The mock response echoes the post-truncation raw_claim, so build
    # it dynamically from what the extractor will pass.
    truncated_claim = long_claim[: ClaimExtractor.MAX_CLAIM_LEN]
    response = _make_pico_dict(
        raw_claim=truncated_claim,
        food=_explicit("coffee", "coffee"),
    )
    extractor = _build_extractor(response, tmp_path)
    pico = extractor.extract(long_claim)

    assert pico.food.value == "coffee"
    assert len(pico.raw_claim) == ClaimExtractor.MAX_CLAIM_LEN

    log_records = [
        json.loads(line)
        for line in (tmp_path / "ext.jsonl").read_text().splitlines()
        if line
    ]
    assert log_records[-1]["truncated"] is True
    assert log_records[-1]["original_length"] == len(long_claim)


# ---------- to_flat() end-to-end ----------

def test_to_flat_drops_slot_extraction_wrappers(tmp_path):
    case = next(c for c in EXTRACTION_TEST_CASES if c.name == "turmeric_inflammation")
    extractor = _build_extractor(case.llm_mock_response, tmp_path)
    pico = extractor.extract(case.claim)

    flat = pico.to_flat()
    assert flat.food == "turmeric"
    assert flat.outcome == "inflammation"
    assert flat.dose is None
    assert set(flat.ambiguous_slots) == set(pico.ambiguous_slots)


# ---------- food normalization override ----------

def test_food_normalization_overrides_llm_output(tmp_path):
    # LLM returns food="curcumin" — extractor must rewrite to "turmeric".
    response = _make_pico_dict(
        raw_claim="Does curcumin help?",
        food=_explicit("curcumin", "curcumin"),
        outcome=_explicit("inflammation", "inflammation"),
    )
    extractor = _build_extractor(response, tmp_path)
    pico = extractor.extract("Does curcumin help?")
    assert pico.food.value == "turmeric"
    # source_span preserves the original substring from the claim.
    assert pico.food.source_span == "curcumin"


def test_food_normalization_typo_rewrite(tmp_path):
    response = _make_pico_dict(
        raw_claim="Is tumeric good?",
        food=_explicit("tumeric", "tumeric"),
    )
    extractor = _build_extractor(response, tmp_path)
    pico = extractor.extract("Is tumeric good?")
    assert pico.food.value == "turmeric"


def test_food_normalization_preserves_canonical_when_already_correct(tmp_path):
    response = _make_pico_dict(
        raw_claim="Is coffee bad?",
        food=_explicit("coffee", "coffee"),
    )
    extractor = _build_extractor(response, tmp_path)
    pico = extractor.extract("Is coffee bad?")
    assert pico.food.value == "coffee"


def test_unknown_food_passes_through(tmp_path):
    response = _make_pico_dict(
        raw_claim="Is zucchini good?",
        food=_explicit("zucchini", "zucchini"),
    )
    extractor = _build_extractor(response, tmp_path)
    pico = extractor.extract("Is zucchini good?")
    # Unknown foods aren't rewritten; they pass through verbatim.
    assert pico.food.value == "zucchini"


# ---------- ambiguous_slots recomputation ----------

def test_ambiguous_slots_recomputed_even_if_llm_lies(tmp_path):
    response = _make_pico_dict(
        raw_claim="Is coffee bad?",
        food=_explicit("coffee", "coffee"),
    )
    # Inject a totally wrong ambiguous_slots from the LLM.
    response["ambiguous_slots"] = ["food", "nonsense"]
    extractor = _build_extractor(response, tmp_path)
    pico = extractor.extract("Is coffee bad?")

    assert "food" not in pico.ambiguous_slots  # food is explicit
    assert "nonsense" not in pico.ambiguous_slots
    # All absent slots should be listed.
    for slot in ("form", "dose", "frequency", "population", "component", "outcome"):
        assert slot in pico.ambiguous_slots


# ---------- scope rejection ----------

def test_scope_rejection_passes_through(tmp_path):
    response = _make_pico_dict(
        raw_claim="Does aspirin prevent heart attacks?",
        is_food_claim=False,
        scope_rejection_reason="Aspirin is a drug, not a food.",
    )
    extractor = _build_extractor(response, tmp_path)
    pico = extractor.extract("Does aspirin prevent heart attacks?")
    assert pico.is_food_claim is False
    assert pico.scope_rejection_reason == "Aspirin is a drug, not a food."


def test_scope_rejection_forces_empty_slots_if_llm_wobbles(tmp_path):
    # LLM claims not-a-food but also fills in a food slot — extractor
    # must scrub the slots to match the rejection shape.
    response = _make_pico_dict(
        raw_claim="Does aspirin prevent heart attacks?",
        food=_explicit("aspirin", "aspirin"),
        is_food_claim=False,
        scope_rejection_reason="Aspirin is a drug.",
    )
    extractor = _build_extractor(response, tmp_path)
    pico = extractor.extract("Does aspirin prevent heart attacks?")
    assert pico.food.value is None
    assert pico.food.confidence == "absent"


# ---------- retry behavior ----------

def test_retry_then_success(tmp_path):
    valid = json.dumps(
        _make_pico_dict(
            raw_claim="Is coffee bad?",
            food=_explicit("coffee", "coffee"),
        )
    )
    extractor = _build_extractor(
        {},
        tmp_path,
        provider_responses=["not json", "also not json", valid],
    )
    pico = extractor.extract("Is coffee bad?")
    assert pico.food.value == "coffee"


# ---------- log format ----------

def test_extraction_log_contains_expected_fields(tmp_path):
    case = next(c for c in EXTRACTION_TEST_CASES if c.name == "coffee_vague")
    extractor = _build_extractor(case.llm_mock_response, tmp_path)
    extractor.extract(case.claim)

    records = [
        json.loads(line)
        for line in (tmp_path / "ext.jsonl").read_text().splitlines()
        if line
    ]
    assert len(records) == 1
    rec = records[0]
    for field in (
        "timestamp",
        "raw_claim",
        "original_length",
        "truncated",
        "pico",
        "food_normalization",
    ):
        assert field in rec


def test_log_records_food_normalization_rewrite(tmp_path):
    response = _make_pico_dict(
        raw_claim="Is tumeric good?",
        food=_explicit("tumeric", "tumeric"),
    )
    extractor = _build_extractor(response, tmp_path)
    extractor.extract("Is tumeric good?")

    rec = json.loads((tmp_path / "ext.jsonl").read_text().splitlines()[-1])
    assert rec["food_normalization"] == {"from": "tumeric", "to": "turmeric"}


def test_log_records_no_normalization_when_canonical(tmp_path):
    response = _make_pico_dict(
        raw_claim="Is coffee bad?",
        food=_explicit("coffee", "coffee"),
    )
    extractor = _build_extractor(response, tmp_path)
    extractor.extract("Is coffee bad?")

    rec = json.loads((tmp_path / "ext.jsonl").read_text().splitlines()[-1])
    assert rec["food_normalization"] is None
