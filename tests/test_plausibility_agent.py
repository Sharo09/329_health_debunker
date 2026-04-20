"""End-to-end tests for the Plausibility orchestrator."""

import json

import pytest

from src.plausibility.mechanism_checker import MechanismJudgment
from src.plausibility.plausibility_agent import PlausibilityAgent
from src.plausibility.reference_table import ReferenceTable
from src.plausibility.schemas import ParsedDose
from src.schemas import PartialPICO


# ---------- fixtures ----------


@pytest.fixture
def table(tmp_path) -> ReferenceTable:
    yaml_text = (
        "apple:\n"
        "  unit: apple\n"
        "  typical_daily_low: 0\n"
        "  typical_daily_high: 3\n"
        "  implausibly_high: 10\n"
        "  harmful_threshold: 20\n"
        "  source: test\n"
        "  notes: test\n"
    )
    path = tmp_path / "ref.yaml"
    path.write_text(yaml_text)
    return ReferenceTable(path=path)


class _ScriptedLLM:
    """Route calls by inspecting the system prompt.

    - If the system prompt mentions "FEASIBILITY", return a
      ``MechanismJudgment``.
    - If it mentions "reasonable for a normal adult" (the generic-dose
      fallback prompt), return whatever ``generic_dose`` is set to.
    - Otherwise, return a ``ParsedDose``.
    """

    def __init__(
        self,
        mechanism: MechanismJudgment,
        dose: ParsedDose | None = None,
        generic_dose=None,
        dose_exception: Exception | None = None,
        mechanism_exception: Exception | None = None,
    ):
        self.mechanism = mechanism
        self.dose = dose
        self.generic_dose = generic_dose
        self.dose_exception = dose_exception
        self.mechanism_exception = mechanism_exception
        self.calls: list[str] = []  # "dose" | "mechanism" | "generic_dose"

    def extract(self, messages, response_schema):
        sys = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "FEASIBILITY" in sys:
            self.calls.append("mechanism")
            if self.mechanism_exception is not None:
                raise self.mechanism_exception
            return self.mechanism
        elif "daily intake of a food" in sys:
            self.calls.append("generic_dose")
            # Default to a "fine" judgment so tests that don't care
            # about the fallback aren't affected by it.
            from src.plausibility.dose_checker import _GenericDoseJudgment
            if self.generic_dose is None:
                return _GenericDoseJudgment(
                    severity="fine", reasoning="fine by default"
                )
            return self.generic_dose
        else:
            self.calls.append("dose")
            if self.dose_exception is not None:
                raise self.dose_exception
            assert self.dose is not None, "no dose response scripted"
            return self.dose


def _ok_judgment() -> MechanismJudgment:
    return MechanismJudgment(
        is_feasible=True, feasibility_reasoning="ok",
        mechanism_is_coherent=True, mechanism_reasoning="ok",
        is_in_scientific_frame=True, frame_reasoning="ok",
    )


def _agent(tmp_path, table, llm) -> PlausibilityAgent:
    return PlausibilityAgent(
        llm_client=llm,
        reference_table=table,
        log_file=str(tmp_path / "plaus.jsonl"),
    )


# ---------- F5 clean pass ----------


def test_f5_clean_pass_no_dose(tmp_path, table):
    llm = _ScriptedLLM(mechanism=_ok_judgment())
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(
        raw_claim="does an apple a day reduce heart disease?",
        food="apple",
    )
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is True
    assert result.failures == []
    assert result.dose_parse is None
    assert llm.calls == ["mechanism"]


def test_f5_clean_pass_with_normal_dose(tmp_path, table):
    llm = _ScriptedLLM(
        mechanism=_ok_judgment(),
        dose=ParsedDose(
            numeric_value=1, unit="apple", time_basis="per day",
            confidence="high", raw_source="1 per day",
        ),
    )
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(
        raw_claim="one apple a day", food="apple", dose="1 per day",
    )
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is True
    assert result.failures == []
    assert result.dose_parse is not None
    # Parallel fan-out — both calls happened, order is nondeterministic.
    assert sorted(llm.calls) == ["dose", "mechanism"]


# ---------- F1 ----------


def test_f1_blocking_alone(tmp_path, table):
    llm = _ScriptedLLM(
        mechanism=_ok_judgment(),
        dose=ParsedDose(
            numeric_value=100, unit="apple", time_basis="per day",
            confidence="high", raw_source="100 apples per day",
        ),
    )
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(
        raw_claim="100 apples per day prevents heart disease",
        food="apple", dose="100 apples per day",
    )
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is False
    assert len(result.failures) == 1
    assert result.failures[0].failure_type == "F1_dose"
    assert result.failures[0].severity == "blocking"


def test_f1_warning_alone_still_proceeds(tmp_path, table):
    llm = _ScriptedLLM(
        mechanism=_ok_judgment(),
        dose=ParsedDose(
            numeric_value=10, unit="apple", time_basis="per day",
            confidence="high", raw_source="10 apples per day",
        ),
    )
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(
        raw_claim="10 apples per day prevents heart disease",
        food="apple", dose="10 apples per day",
    )
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is True
    assert len(result.failures) == 1
    assert result.failures[0].severity == "warning"
    assert len(result.warnings) == 1


# ---------- F3, F4 alone ----------


def test_f3_alone_blocks(tmp_path, table):
    llm = _ScriptedLLM(
        mechanism=MechanismJudgment(
            is_feasible=True, feasibility_reasoning="ok",
            mechanism_is_coherent=False, mechanism_reasoning="pH homeostasis",
            is_in_scientific_frame=True, frame_reasoning="ok",
        ),
    )
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(raw_claim="alkaline water cures cancer")
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is False
    assert [f.failure_type for f in result.failures] == ["F3_mechanism"]


def test_f1_blocking_plus_f3(tmp_path, table):
    llm = _ScriptedLLM(
        mechanism=MechanismJudgment(
            is_feasible=True, feasibility_reasoning="ok",
            mechanism_is_coherent=False, mechanism_reasoning="incoherent",
            is_in_scientific_frame=True, frame_reasoning="ok",
        ),
        dose=ParsedDose(
            numeric_value=100, unit="apple", time_basis="per day",
            confidence="high", raw_source="100",
        ),
    )
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(
        raw_claim="100 apples a day cures cancer by balancing chakras",
        food="apple", dose="100",
    )
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is False
    types = sorted(f.failure_type for f in result.failures)
    assert types == ["F1_dose", "F3_mechanism"]


# ---------- fail-open behaviour ----------


def test_missing_dose_skips_f1_cleanly(tmp_path, table):
    llm = _ScriptedLLM(mechanism=_ok_judgment())
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(raw_claim="apples are healthy", food="apple")
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is True
    assert result.failures == []
    # No dose parse call happened.
    assert "dose" not in llm.calls


def test_food_not_in_table_skips_f1(tmp_path, table):
    llm = _ScriptedLLM(
        mechanism=_ok_judgment(),
        dose=ParsedDose(
            numeric_value=999, unit="kumquat", time_basis="per day",
            confidence="high", raw_source="999 kumquats",
        ),
    )
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(
        raw_claim="999 kumquats cure everything",
        food="kumquat", dose="999 kumquats",
    )
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is True
    assert result.failures == []


def test_dose_parse_failure_falls_through_to_mechanism(tmp_path, table):
    llm = _ScriptedLLM(
        mechanism=_ok_judgment(),
        dose_exception=RuntimeError("parse fail"),
    )
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(
        raw_claim="something", food="apple", dose="mumble",
    )
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is True
    assert result.failures == []
    assert sorted(llm.calls) == ["dose", "mechanism"]


def test_mechanism_failure_fails_open(tmp_path, table):
    llm = _ScriptedLLM(
        mechanism=_ok_judgment(),
        mechanism_exception=RuntimeError("mech fail"),
    )
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(raw_claim="anything")
    result = agent.evaluate(pico)
    assert result.should_proceed_to_pipeline is True
    assert result.failures == []


# ---------- logging ----------


def test_log_file_is_written(tmp_path, table):
    log_file = tmp_path / "nested" / "plaus.jsonl"
    llm = _ScriptedLLM(mechanism=_ok_judgment())
    agent = PlausibilityAgent(
        llm_client=llm, reference_table=table, log_file=str(log_file),
    )
    pico = PartialPICO(raw_claim="is coffee healthy?", food="coffee")
    agent.evaluate(pico)
    assert log_file.exists()
    line = log_file.read_text().strip()
    record = json.loads(line)
    assert record["raw_claim"] == "is coffee healthy?"
    assert "result" in record
    assert "pico" in record


# ---------- summary ----------


def test_summary_text_for_clean_pass(tmp_path, table):
    llm = _ScriptedLLM(mechanism=_ok_judgment())
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(raw_claim="apple a day")
    result = agent.evaluate(pico)
    assert "worth investigating" in result.reasoning_summary


def test_summary_text_for_block(tmp_path, table):
    llm = _ScriptedLLM(
        mechanism=MechanismJudgment(
            is_feasible=True, feasibility_reasoning="ok",
            mechanism_is_coherent=False, mechanism_reasoning="pH",
            is_in_scientific_frame=True, frame_reasoning="ok",
        ),
    )
    agent = _agent(tmp_path, table, llm)
    pico = PartialPICO(raw_claim="alkaline water cures cancer")
    result = agent.evaluate(pico)
    assert "halted" in result.reasoning_summary.lower()
    assert "F3_mechanism" in result.reasoning_summary
