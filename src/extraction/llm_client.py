"""Thin LLM wrapper with structured output, parse-failure retries, and audit logging.

The default provider targets Gemini via ``google-generativeai``; tests
inject a mock callable to avoid real API calls. All calls are appended
to ``logs/extraction_llm.jsonl`` as a JSON record per attempt.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from pydantic import BaseModel

from src.extraction.errors import ExtractionError

logger = logging.getLogger(__name__)

DEFAULT_LOG_FILE = "logs/extraction_llm.jsonl"
MAX_RETRIES = 3
RETRY_REMINDER = (
    "Your previous response did not parse as valid JSON. "
    "Return ONLY the JSON object that matches the required schema, "
    "with no surrounding prose or markdown fences."
)

# Provider signature: (messages, response_schema, model, temperature) -> raw string.
ProviderCallable = Callable[[list[dict], type[BaseModel], str, float], str]


def _default_gemini_provider(
    messages: list[dict],
    response_schema: type[BaseModel],
    model: str,
    temperature: float,
) -> str:
    """Default provider — calls Gemini via the ``google-genai`` SDK.

    Picks up ``GOOGLE_API_KEY`` / ``GEMINI_API_KEY`` from the
    environment automatically. The older ``google-generativeai``
    package is deprecated and can't serialize pydantic schemas that
    include default-valued fields; the new ``google-genai`` package
    handles pydantic classes natively.
    """
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as e:
        raise ImportError(
            "google-genai is not installed. Install it with "
            "`pip install google-genai` or pass a custom provider "
            "callable to LLMClient(provider=...)."
        ) from e

    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    system_instruction = "\n\n".join(system_parts) if system_parts else None

    contents: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    client = genai.Client()
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=response_schema,
            system_instruction=system_instruction,
        ),
    )
    return response.text


class LLMClient:
    def __init__(
        self,
        model: str = "gemini-2.5-pro",
        temperature: float = 0.0,
        log_file: Optional[str] = None,
        provider: Optional[ProviderCallable] = None,
    ):
        self.model = model
        self.temperature = temperature
        self.log_file = log_file if log_file is not None else DEFAULT_LOG_FILE
        self._provider: ProviderCallable = provider or _default_gemini_provider

    def extract(
        self,
        messages: list[dict],
        response_schema: type[BaseModel],
    ) -> BaseModel:
        """Call the LLM and parse its output against ``response_schema``.

        Retries up to ``MAX_RETRIES`` times on parse failures, each time
        appending a reminder. Raises ``ExtractionError`` if all attempts
        fail, or if the provider itself raises (no retry on transport
        errors — those surface immediately).
        """
        current_messages = list(messages)
        last_error: Optional[str] = None

        for attempt in range(MAX_RETRIES):
            t0 = time.monotonic()

            try:
                raw = self._provider(
                    current_messages, response_schema, self.model, self.temperature
                )
            except Exception as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                self._log(
                    current_messages,
                    raw_response=None,
                    parsed=None,
                    error=f"{type(exc).__name__}: {exc}",
                    attempt=attempt,
                    latency_ms=latency_ms,
                )
                raise ExtractionError(
                    f"LLM provider call failed: {type(exc).__name__}: {exc}"
                ) from exc

            parsed: Optional[BaseModel] = None
            error: Optional[str] = None
            try:
                parsed = response_schema.model_validate_json(raw)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            latency_ms = (time.monotonic() - t0) * 1000
            self._log(
                current_messages,
                raw_response=raw,
                parsed=parsed,
                error=error,
                attempt=attempt,
                latency_ms=latency_ms,
            )

            if parsed is not None:
                return parsed

            logger.warning(
                "LLM parse failure on attempt %d/%d: %s", attempt + 1, MAX_RETRIES, error
            )
            last_error = error
            current_messages = current_messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": RETRY_REMINDER},
            ]

        raise ExtractionError(
            f"LLM failed to return valid {response_schema.__name__} JSON "
            f"after {MAX_RETRIES} attempts. Last error: {last_error}"
        )

    def _log(
        self,
        messages: list[dict],
        raw_response: Optional[str],
        parsed: Optional[BaseModel],
        error: Optional[str],
        attempt: int,
        latency_ms: float,
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self.model,
            "temperature": self.temperature,
            "attempt": attempt,
            "messages": messages,
            "raw_response": raw_response,
            "parsed": parsed.model_dump() if parsed is not None else None,
            "error": error,
            "latency_ms": latency_ms,
        }
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
