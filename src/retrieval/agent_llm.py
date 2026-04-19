"""Thin tool-calling LLM abstraction for the retrieval agent.

Two implementations:
  - ``GeminiAgentLLM`` — real Gemini function-calling via ``google-genai``
  - ``ScriptedAgentLLM`` — deterministic test double that replays
                            pre-baked tool calls

The agent loop in ``retrieval_agent.py`` talks to this interface
only, so the loop is LLM-vendor agnostic and unit-testable without any
network calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class Stop:
    text: str = ""


AgentAction = ToolCall | Stop


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class AgentLLM:
    """Picks the next action given the running conversation and tool catalogue."""

    def next_action(
        self,
        system_prompt: str,
        messages: list[dict],
        tool_declarations: list[dict],
    ) -> AgentAction:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Scripted implementation (tests)
# ---------------------------------------------------------------------------

class ScriptedAgentLLM(AgentLLM):
    """Returns pre-baked actions in order. Used only in tests."""

    def __init__(self, actions: list[AgentAction]):
        self._actions: list[AgentAction] = list(actions)
        self.call_count = 0

    def next_action(self, system_prompt, messages, tool_declarations) -> AgentAction:
        self.call_count += 1
        if not self._actions:
            return Stop(text="scripted agent exhausted")
        return self._actions.pop(0)


# ---------------------------------------------------------------------------
# Gemini implementation
# ---------------------------------------------------------------------------

class GeminiAgentLLM(AgentLLM):
    """Function-calling Gemini via ``google-genai``.

    Caches the ``genai.Client`` as a module-level singleton so successive
    agent calls don't step on each other's httpx state (same workaround
    we use in the synthesis module).
    """

    _cached_client: Any = None

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def next_action(self, system_prompt, messages, tool_declarations) -> AgentAction:
        from google import genai
        from google.genai import types as gtypes

        if GeminiAgentLLM._cached_client is None:
            GeminiAgentLLM._cached_client = genai.Client()
        client = GeminiAgentLLM._cached_client

        function_decls = [
            gtypes.FunctionDeclaration(
                name=d["name"],
                description=d["description"],
                parameters=d["parameters"],
            )
            for d in tool_declarations
        ]
        tool = gtypes.Tool(function_declarations=function_decls)

        contents = _messages_to_contents(messages)

        # Retry on Gemini 429s with Retry-After honoured.
        from src.retrieval._gemini_retry import call_with_429_retry

        response = call_with_429_retry(
            lambda: client.models.generate_content(
                model=self.model,
                contents=contents,
                config=gtypes.GenerateContentConfig(
                    tools=[tool],
                    system_instruction=system_prompt,
                    temperature=0.0,
                ),
            )
        )

        # Walk the response for a function call; otherwise take the text.
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return Stop(text="no candidates returned")
        parts = getattr(candidates[0].content, "parts", []) or []
        text_parts: list[str] = []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc:
                args = dict(getattr(fc, "args", None) or {})
                return ToolCall(name=fc.name, args=args)
            txt = getattr(part, "text", None)
            if txt:
                text_parts.append(txt)
        return Stop(text="\n".join(text_parts))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _messages_to_contents(messages: list[dict]) -> list[Any]:
    """Translate our internal message dicts to google-genai Content objects.

    Internal shape:
        {"role": "user"|"model", "parts": [{"text": "..."}]}
        {"role": "model", "parts": [{"function_call": {"name": ..., "args": ...}}]}
        {"role": "user",  "parts": [{"function_response": {"name": ..., "response": ...}}]}
    """
    from google.genai import types as gtypes

    contents = []
    for m in messages:
        role = m["role"]
        parts = []
        for p in m["parts"]:
            if "text" in p:
                parts.append(gtypes.Part(text=p["text"]))
            elif "function_call" in p:
                fc = p["function_call"]
                parts.append(
                    gtypes.Part(
                        function_call=gtypes.FunctionCall(
                            name=fc["name"], args=fc["args"]
                        )
                    )
                )
            elif "function_response" in p:
                fr = p["function_response"]
                parts.append(
                    gtypes.Part.from_function_response(
                        name=fr["name"], response=fr["response"]
                    )
                )
        contents.append(gtypes.Content(role=role, parts=parts))
    return contents
