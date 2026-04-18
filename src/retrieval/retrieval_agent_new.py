"""The new retrieval agent — Station 3's agentic retrieval loop.

Rebuilt per ``docs/retrieval_spec.md``. Replaces the legacy
``retrieval_agent.py`` in Task 10; kept in a sibling file until the
swap so Sharon's code keeps working during development.

Flow
----
1. Resolve every PICO slot to a validated ``Concept`` (orange → Citrus sinensis, etc.).
2. Initialise an ``AgentState`` with those concepts.
3. Loop: ask the LLM for the next tool call, execute it, append the result
   back to the conversation. Stop on ``finish`` / max iterations / max tool
   calls / the LLM stops calling tools.
4. Fetch full abstracts for the accumulated PMIDs.
5. Run CAERS in parallel via a thread (non-blocking; failures are swallowed).
6. Log an audit record to ``logs/retrieval.jsonl``.
7. Return a ``RetrievalResultV2``.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from src.extraction.llm_client import LLMClient
from src.retrieval.agent_llm import AgentLLM, GeminiAgentLLM, Stop, ToolCall
from src.retrieval.agent_state import AgentState, ExecutedQuery
from src.retrieval.caers_client import CAERSClient
from src.retrieval.concept_query_builder import QueryBuilder
from src.retrieval.concept_resolver import ConceptResolver
from src.retrieval.pubmed_client import PubMedClient
from src.retrieval.retrieval_tools import TOOL_DECLARATIONS, RetrievalTools
from src.retrieval.schemas import (
    CAERSReport,
    ExecutedQueryModel,
    RetrievalResultV2,
    RetrievedPaper,
)
from src.schemas import PartialPICO

logger = logging.getLogger(__name__)

DEFAULT_LOG_FILE = "logs/retrieval.jsonl"
DEFAULT_MODEL = "gemini-2.5-flash"


_SYSTEM_PROMPT = """\
You are Station 3 of a food/nutrition claim fact-checker. Your job is to
find a diverse, relevant set of research papers for a given claim, using
PubMed via the tools provided.

The claim has already been resolved into MeSH CONCEPTS by an upstream
module. You do NOT construct PubMed query strings by hand — use the
``plan_query`` tool, which takes concept slot names ("food", "outcome",
"component", "related_outcome") and lets the query builder handle syntax.

STRATEGIES

Whenever a "component" concept is present (e.g., vitamin C, curcumin,
caffeine), the mechanism and component-related-outcome queries are the
single highest-yield paths — the core literature is almost always
indexed under the component, NOT under the whole food. Exhaust these
before concluding anything.

Run queries in this order when a component exists:

1. Direct query        plan_query(slots=["food","outcome"])
2. Mechanism query     plan_query(slots=["component","outcome"])
3. Component + broader  get_related_concept(slot_name="outcome", direction="broader")
                        plan_query(slots=["component","related_outcome"])      ← HIGH YIELD
4. Component + sibling  get_related_concept(slot_name="outcome", direction="sibling")
                        plan_query(slots=["component","related_outcome_2"])     ← also HIGH YIELD
                        (skip if 1–3 already produced 20+ papers)
5. Food + related      plan_query(slots=["food","related_outcome"])
                        (lower yield — only as diversification)
6. Relax filters       include_filters=False or drop study_tiers (last resort)

When no component exists, skip 2–4 and use 1, 5, 6 only.

PRODUCTIVE-QUERY RULE
---------------------
When a component concept is present and validated, you MUST execute at
least ONE of strategies (2), (3), or (4) productively before calling
finish. A direct food query alone does not give the agent credit for a
"mechanism path explored". Failing to run a component query is the
single most common way this system produces wrong verdicts.

HARD STOPPING RULE (you cannot finish until you pass this)
----------------------------------------------------------
You MUST execute at least 2 PRODUCTIVE QUERIES before calling finish.
A query is "productive" if it adds ≥5 NEW PMIDs to the accumulated set.
``pubmed_search`` returns a ``productive`` boolean and a running count
(``productive_queries_so_far``) — watch these values.

If your direct query was unproductive, you MUST try the mechanism
query OR a related-outcome query before finishing. Returning a small
set of mostly-irrelevant direct-query hits is NOT acceptable.

The ONLY exception: if you've tried direct + mechanism + one related
concept and still have fewer than 5 new PMIDs across all three, call
finish with a rationale containing the string "below_threshold" and
the system will accept the early finish.

DO NOT REPEAT THE SAME TOOL CALL
--------------------------------
The system rejects identical tool calls (same tool, same arguments).
If you want to try the same strategy with a twist, CHANGE something —
different slots, different direction, a different study_tiers filter.

PROCESS

- Always call pubmed_count on a planned query BEFORE pubmed_search when
  you're unsure whether it's productive. If the count is 0 or >100,000,
  reconsider before spending a search call.
- Aim for 15–40 unique, relevant papers including at least one RCT,
  systematic review, or meta-analysis (use study_tiers=[1,2] to bias).
- Call get_related_concept AT MOST TWICE total per run.

Do NOT pad with irrelevant papers. A small-but-relevant set beats a
bloated-but-irrelevant one.
"""


class RetrievalAgent:
    """LLM tool-use loop that retrieves papers from PubMed."""

    def __init__(
        self,
        llm: Optional[AgentLLM] = None,
        pubmed: Optional[PubMedClient] = None,
        resolver: Optional[ConceptResolver] = None,
        builder: Optional[QueryBuilder] = None,
        caers: Optional[CAERSClient] = None,
        model: str = DEFAULT_MODEL,
        log_file: Optional[str] = None,
        run_caers_in_parallel: bool = True,
    ):
        self.llm = llm or GeminiAgentLLM(model=model)
        self.pubmed = pubmed or PubMedClient()
        self.builder = builder or QueryBuilder()
        if resolver is None:
            resolver = ConceptResolver(LLMClient(model=model), self.pubmed)
        self.resolver = resolver
        self.caers = caers
        self.log_file = log_file if log_file is not None else DEFAULT_LOG_FILE
        self.run_caers_in_parallel = run_caers_in_parallel

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def retrieve(self, pico: PartialPICO) -> RetrievalResultV2:
        # 1. Resolve every PICO slot to a Concept.
        concepts = self.resolver.resolve_pico(pico)

        # 2. Prepare state and tools.
        state = AgentState(locked_pico=pico, concepts=concepts)
        tools = RetrievalTools(self.pubmed, self.resolver, self.builder, state)

        # 3. Fire CAERS off in a background thread while the agent works.
        caers_future = None
        if self.caers is not None and self.run_caers_in_parallel and pico.food:
            self._caers_pool = ThreadPoolExecutor(max_workers=1)
            caers_future = self._caers_pool.submit(
                self._caers_safe, pico.food
            )

        # 4. Agent loop.
        self._run_loop(state, tools)

        # 5. Fetch full abstracts for accumulated PMIDs.
        papers = self._finalize_papers(state)

        # 6. Collect CAERS result.
        caers_reports = self._collect_caers(caers_future, pico)

        # 7. Build result.
        result = RetrievalResultV2(
            locked_pico=pico,
            concept_resolutions=concepts,
            queries_executed=[
                ExecutedQueryModel(**vars(q)) for q in state.executed_queries
            ],
            papers=papers,
            caers_reports=caers_reports,
            retrieval_notes=list(state.retrieval_notes),
            total_iterations=state.iterations,
            budget_exhausted=state.budget_exhausted,
            finish_rationale=state.finish_rationale,
        )

        # 8. Audit log.
        self._log(result, state)

        return result

    # ------------------------------------------------------------------
    # Agent loop
    # ------------------------------------------------------------------

    def _run_loop(self, state: AgentState, tools: RetrievalTools) -> None:
        messages: list[dict] = [
            {"role": "user", "parts": [{"text": self._initial_prompt(state)}]}
        ]

        while True:
            if state.finished:
                break
            if state.iterations >= state.max_iterations:
                state.budget_exhausted = True
                state.retrieval_notes.append(
                    f"Stopped: reached max_iterations={state.max_iterations}"
                )
                break
            if len(state.tool_call_log) >= state.max_tool_calls:
                state.budget_exhausted = True
                state.retrieval_notes.append(
                    f"Stopped: reached max_tool_calls={state.max_tool_calls}"
                )
                break

            action = self.llm.next_action(
                _SYSTEM_PROMPT, messages, TOOL_DECLARATIONS
            )

            if isinstance(action, Stop):
                state.retrieval_notes.append(
                    f"LLM stopped without finish: {action.text[:200]!r}"
                )
                break

            assert isinstance(action, ToolCall)
            result = tools.dispatch(action.name, action.args)

            # Append a model turn (the tool call) and a user turn (the response)
            # so the next LLM call sees the full trace.
            messages.append(
                {
                    "role": "model",
                    "parts": [
                        {
                            "function_call": {
                                "name": action.name,
                                "args": action.args,
                            }
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "name": action.name,
                                "response": result,
                            }
                        }
                    ],
                }
            )
            state.iterations += 1

    # ------------------------------------------------------------------
    # Post-loop
    # ------------------------------------------------------------------

    def _finalize_papers(self, state: AgentState) -> list[RetrievedPaper]:
        pmids = sorted(state.accumulated_pmids)
        if not pmids:
            return []
        records = self.pubmed.fetch_details(pmids)
        papers: list[RetrievedPaper] = []
        for r in records:
            pmid = r.get("pmid") or ""
            papers.append(
                RetrievedPaper(
                    pmid=pmid,
                    title=r.get("title", "") or "",
                    abstract=r.get("abstract", "") or "",
                    pub_types=list(r.get("pub_types", []) or []),
                    journal=r.get("journal", "") or "",
                    year=r.get("year"),
                    authors=list(r.get("authors", []) or []),
                    is_retracted="Retracted Publication" in (r.get("pub_types") or []),
                    source_query=state.pmid_source.get(pmid, ""),
                )
            )
        return papers

    # ------------------------------------------------------------------
    # CAERS
    # ------------------------------------------------------------------

    def _caers_safe(self, product_term: str) -> list[CAERSReport]:
        try:
            return self.caers.search_by_product(product_term, limit=50)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("CAERS retrieval failed: %s", exc)
            return []

    def _collect_caers(self, future, pico: PartialPICO) -> list[CAERSReport]:
        if future is None:
            # Sync fallback if parallelism was disabled.
            if self.caers is not None and pico.food:
                return self._caers_safe(pico.food)
            return []
        try:
            reports = future.result(timeout=30)
        except Exception as exc:
            logger.warning("CAERS future failed: %s", exc)
            reports = []
        finally:
            try:
                self._caers_pool.shutdown(wait=False)
            except Exception:
                pass
        return reports

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    def _initial_prompt(self, state: AgentState) -> str:
        pico = state.locked_pico
        lines = [
            f"CLAIM: {pico.raw_claim}",
            "",
            "RESOLVED CONCEPTS:",
        ]
        for slot, concept in sorted(state.concepts.items()):
            lines.append(
                f"  {slot}: user_term={concept.user_term!r} "
                f"mesh={concept.mesh_terms} "
                f"tiab={concept.tiab_synonyms[:3]} "
                f"validated={concept.validated}"
            )
        lines.extend(
            [
                "",
                "Decide a retrieval strategy and call the tools. When you "
                "have a diverse, relevant paper set, call finish(rationale=...).",
            ]
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, result: RetrievalResultV2, state: AgentState) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_claim": result.locked_pico.raw_claim,
            "locked_pico": result.locked_pico.model_dump(),
            "concepts_resolved": {
                k: v.model_dump() for k, v in result.concept_resolutions.items()
            },
            "agent_iterations": result.total_iterations,
            "tool_calls": state.tool_call_log,
            "queries_executed": [q.model_dump() for q in result.queries_executed],
            "final_paper_count": len(result.papers),
            "caers_report_count": len(result.caers_reports),
            "budget_exhausted": result.budget_exhausted,
            "finish_rationale": result.finish_rationale,
            "retrieval_notes": result.retrieval_notes,
        }
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
