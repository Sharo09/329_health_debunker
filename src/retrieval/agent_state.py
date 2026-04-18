"""Shared agent state passed between RetrievalAgent and RetrievalTools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from src.retrieval.schemas import Concept
from src.schemas import PartialPICO


@dataclass
class ExecutedQuery:
    """One PubMed query the agent actually ran, for audit trail."""

    query_string: str
    rationale: str
    hit_count: int
    papers_fetched: int
    pmids: list[str] = field(default_factory=list)


@dataclass
class AgentState:
    """Mutable state carried through the agent loop.

    ``concepts`` is a mutable dict because ``get_related_concept`` adds new
    entries under keys like ``"related_outcome"`` during the loop.
    """

    locked_pico: PartialPICO
    concepts: dict[str, Concept]
    iterations: int = 0
    max_iterations: int = 8
    max_tool_calls: int = 20
    # A productive query adds ≥ PRODUCTIVE_QUERY_MIN_NEW new PMIDs. The
    # agent cannot call finish until ``productive_queries >= MIN_PRODUCTIVE_TO_FINISH``.
    productive_queries: int = 0
    min_productive_to_finish: int = 2
    accumulated_pmids: set[str] = field(default_factory=set)
    pmid_source: dict[str, str] = field(default_factory=dict)  # pmid → query that first found it
    executed_queries: list[ExecutedQuery] = field(default_factory=list)
    tool_call_log: list[dict] = field(default_factory=list)
    # Fingerprint (name + sorted args) of every tool call so we can reject
    # identical repeats and force the agent to try a different strategy.
    prior_tool_fingerprints: set[str] = field(default_factory=set)
    retrieval_notes: list[str] = field(default_factory=list)
    finished: bool = False
    finish_rationale: Optional[str] = None
    budget_exhausted: bool = False

    def log_tool_call(self, name: str, args: dict, result: Any) -> None:
        self.tool_call_log.append(
            {
                "iteration": self.iterations,
                "tool": name,
                "args": dict(args),
                "result_summary": _summarise(result),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


PRODUCTIVE_QUERY_MIN_NEW = 5  # new PMIDs a query must add to count as productive


def _summarise(result: Any) -> Any:
    """Trim big result payloads for the log (full payloads live elsewhere)."""
    if not isinstance(result, dict):
        return result
    trimmed = {}
    for k, v in result.items():
        if isinstance(v, list) and len(v) > 10:
            trimmed[k] = {"_list_len": len(v), "_first_3": v[:3]}
        else:
            trimmed[k] = v
    return trimmed
