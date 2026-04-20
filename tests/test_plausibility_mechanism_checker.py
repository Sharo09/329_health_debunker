"""Tests for the F2/F3/F4 mechanism checker."""

import pytest

from src.plausibility.mechanism_checker import (
    MechanismJudgment,
    check_mechanism,
)


class _FakeLLM:
    def __init__(self, judgment: MechanismJudgment):
        self._judgment = judgment
        self.calls: list[list[dict]] = []

    def extract(self, messages, response_schema):
        assert response_schema is MechanismJudgment
        self.calls.append([dict(m) for m in messages])
        return self._judgment


def _j(**overrides) -> MechanismJudgment:
    base = dict(
        is_feasible=True,
        feasibility_reasoning="ok",
        mechanism_is_coherent=True,
        mechanism_reasoning="ok",
        is_in_scientific_frame=True,
        frame_reasoning="ok",
    )
    base.update(overrides)
    return MechanismJudgment(**base)


# ---------- no failures ----------


def test_all_pass_returns_empty():
    llm = _FakeLLM(_j())
    assert check_mechanism("does an apple a day reduce heart disease?", llm) == []


# ---------- individual failures ----------


def test_f2_only():
    llm = _FakeLLM(_j(is_feasible=False, feasibility_reasoning="40-day fast"))
    fs = check_mechanism("fast for 40 days", llm)
    assert [f.failure_type for f in fs] == ["F2_feasibility"]
    assert fs[0].severity == "warning"
    assert fs[0].reasoning == "40-day fast"
    assert "raw_judgment" in fs[0].supporting_data


def test_f3_only():
    llm = _FakeLLM(_j(mechanism_is_coherent=False, mechanism_reasoning="pH homeostasis"))
    fs = check_mechanism("alkaline water cures cancer", llm)
    assert [f.failure_type for f in fs] == ["F3_mechanism"]
    assert fs[0].severity == "blocking"
    assert fs[0].reasoning == "pH homeostasis"


def test_f4_only():
    llm = _FakeLLM(_j(is_in_scientific_frame=False, frame_reasoning="undefined terms"))
    fs = check_mechanism("crystal vibrations", llm)
    assert [f.failure_type for f in fs] == ["F4_frame"]
    assert fs[0].severity == "blocking"
    assert fs[0].reasoning == "undefined terms"


# ---------- combinations ----------


def test_f3_and_f4_together():
    llm = _FakeLLM(_j(
        mechanism_is_coherent=False, mechanism_reasoning="incoherent",
        is_in_scientific_frame=False, frame_reasoning="out of frame",
    ))
    fs = check_mechanism("vibrations reverse cancer", llm)
    types = [f.failure_type for f in fs]
    assert types == ["F3_mechanism", "F4_frame"]
    assert all(f.severity == "blocking" for f in fs)


def test_all_three_fail():
    llm = _FakeLLM(_j(
        is_feasible=False, feasibility_reasoning="infeasible",
        mechanism_is_coherent=False, mechanism_reasoning="incoherent",
        is_in_scientific_frame=False, frame_reasoning="out of frame",
    ))
    fs = check_mechanism("x", llm)
    assert [f.failure_type for f in fs] == [
        "F2_feasibility", "F3_mechanism", "F4_frame",
    ]
    assert [f.severity for f in fs] == ["warning", "blocking", "blocking"]


def test_prompt_sent_to_llm():
    llm = _FakeLLM(_j())
    check_mechanism("my claim", llm)
    assert len(llm.calls) == 1
    msgs = llm.calls[0]
    assert msgs[0]["role"] == "system"
    assert "FEASIBILITY" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert "my claim" in msgs[1]["content"]
