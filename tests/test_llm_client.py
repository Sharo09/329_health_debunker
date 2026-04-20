"""Tests for the LLM client wrapper (Task 4)."""

import json

import pytest
from pydantic import BaseModel

from src.extraction.errors import ExtractionError
from src.extraction.llm_client import (
    MAX_RETRIES,
    RETRY_REMINDER,
    LLMClient,
)


class _Simple(BaseModel):
    value: str
    count: int


def _scripted_provider(responses: list[str]):
    """Return a provider callable that yields ``responses`` in order."""
    pending = list(responses)
    calls: list[dict] = []

    def provider(messages, response_schema, model, temperature):
        calls.append(
            {
                "messages": [dict(m) for m in messages],
                "model": model,
                "temperature": temperature,
                "schema": response_schema.__name__,
            }
        )
        if not pending:
            raise AssertionError("scripted provider ran out of responses")
        return pending.pop(0)

    provider.calls = calls  # type: ignore[attr-defined]
    return provider


def _raising_provider(exc: Exception):
    def provider(messages, response_schema, model, temperature):
        raise exc

    return provider


# ---------- happy path ----------

def test_first_attempt_success(tmp_path):
    valid = json.dumps({"value": "ok", "count": 2})
    provider = _scripted_provider([valid])
    client = LLMClient(
        model="test-model",
        temperature=0.0,
        log_file=str(tmp_path / "llm.jsonl"),
        provider=provider,
    )

    result = client.extract([{"role": "user", "content": "go"}], _Simple)

    assert isinstance(result, _Simple)
    assert result.value == "ok"
    assert result.count == 2
    assert len(provider.calls) == 1


def test_log_entry_contains_expected_fields(tmp_path):
    log_file = tmp_path / "llm.jsonl"
    valid = json.dumps({"value": "ok", "count": 1})
    client = LLMClient(
        model="test-model",
        temperature=0.0,
        log_file=str(log_file),
        provider=_scripted_provider([valid]),
    )
    client.extract([{"role": "user", "content": "go"}], _Simple)

    records = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    assert len(records) == 1
    rec = records[0]
    for field in (
        "timestamp",
        "model",
        "temperature",
        "attempt",
        "messages",
        "raw_response",
        "parsed",
        "error",
        "latency_ms",
    ):
        assert field in rec, f"missing log field: {field}"
    assert rec["model"] == "test-model"
    assert rec["temperature"] == 0.0
    assert rec["attempt"] == 0
    assert rec["parsed"] == {"value": "ok", "count": 1}
    assert rec["error"] is None
    assert rec["latency_ms"] >= 0


# ---------- retry behavior ----------

def test_retries_twice_then_succeeds(tmp_path):
    provider = _scripted_provider(
        [
            "not json at all",
            "also not json",
            json.dumps({"value": "ok", "count": 3}),
        ]
    )
    log_file = tmp_path / "llm.jsonl"
    client = LLMClient(
        model="test",
        log_file=str(log_file),
        provider=provider,
    )
    result = client.extract([{"role": "user", "content": "go"}], _Simple)

    assert result.value == "ok"
    assert result.count == 3
    assert len(provider.calls) == 3

    # Retry should append a reminder for each failed attempt.
    second_call = provider.calls[1]
    third_call = provider.calls[2]
    assert any(m["content"] == RETRY_REMINDER for m in second_call["messages"])
    assert (
        sum(1 for m in third_call["messages"] if m["content"] == RETRY_REMINDER) == 2
    )

    # One log record per attempt.
    records = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    assert len(records) == 3
    assert records[0]["attempt"] == 0
    assert records[1]["attempt"] == 1
    assert records[2]["attempt"] == 2
    assert records[0]["error"] is not None
    assert records[1]["error"] is not None
    assert records[2]["error"] is None


def test_three_parse_failures_raises_extraction_error(tmp_path):
    provider = _scripted_provider(["garbage", "more garbage", "still garbage"])
    client = LLMClient(
        provider=provider,
        log_file=str(tmp_path / "llm.jsonl"),
    )

    with pytest.raises(ExtractionError) as exc:
        client.extract([{"role": "user", "content": "x"}], _Simple)
    assert str(MAX_RETRIES) in str(exc.value)
    assert len(provider.calls) == MAX_RETRIES


def test_valid_json_but_schema_mismatch_also_retries(tmp_path):
    # Valid JSON but missing required fields -> ValidationError -> retry.
    bad = json.dumps({"wrong_field": "x"})
    good = json.dumps({"value": "ok", "count": 1})
    provider = _scripted_provider([bad, good])
    client = LLMClient(
        provider=provider,
        log_file=str(tmp_path / "llm.jsonl"),
    )
    result = client.extract([{"role": "user", "content": "x"}], _Simple)
    assert result.value == "ok"


# ---------- provider failures ----------

def test_provider_exception_surfaces_as_extraction_error(tmp_path):
    log_file = tmp_path / "llm.jsonl"
    client = LLMClient(
        provider=_raising_provider(RuntimeError("network down")),
        log_file=str(log_file),
    )
    with pytest.raises(ExtractionError) as exc:
        client.extract([{"role": "user", "content": "x"}], _Simple)
    assert "network down" in str(exc.value)

    # Provider failures do NOT retry — one log entry only.
    records = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    assert len(records) == 1
    assert records[0]["raw_response"] is None
    assert "RuntimeError" in records[0]["error"]


# ---------- defaults ----------

def test_default_model_and_temperature():
    client = LLMClient(provider=_scripted_provider([]))
    assert client.model == "gemini-3.1-flash-lite-preview"
    assert client.temperature == 0.0


def test_provider_receives_model_and_temperature(tmp_path):
    valid = json.dumps({"value": "ok", "count": 1})
    provider = _scripted_provider([valid])
    client = LLMClient(
        model="custom-model",
        temperature=0.3,
        provider=provider,
        log_file=str(tmp_path / "llm.jsonl"),
    )
    client.extract([{"role": "user", "content": "go"}], _Simple)
    assert provider.calls[0]["model"] == "custom-model"
    assert provider.calls[0]["temperature"] == 0.3


def test_log_dir_auto_created(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "llm.jsonl"
    client = LLMClient(
        provider=_scripted_provider([json.dumps({"value": "ok", "count": 0})]),
        log_file=str(nested),
    )
    client.extract([{"role": "user", "content": "x"}], _Simple)
    assert nested.exists()
