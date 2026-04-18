"""Tools the retrieval agent LLM can invoke via function calling.

Each tool is a method on ``RetrievalTools``; a single ``dispatch`` entry
point routes tool-name + args from the LLM to the right method and
appends a log entry to ``AgentState.tool_call_log``.

The higher-level ``plan_query`` tool abstracts query construction: the
agent names which concepts to combine (by slot key), and ``QueryBuilder``
produces the PubMed syntax. This prevents the agent from reintroducing
the string-concatenation bugs we just fixed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.retrieval.agent_state import (
    PRODUCTIVE_QUERY_MIN_NEW,
    AgentState,
    ExecutedQuery,
)
from src.retrieval.concept_query_builder import QueryBuilder
from src.retrieval.concept_resolver import ConceptResolver
from src.retrieval.pubmed_client import PubMedClient
from src.retrieval.schemas import Concept

logger = logging.getLogger(__name__)


class RetrievalTools:
    """Callable tools the agent uses during the retrieval loop."""

    def __init__(
        self,
        pubmed: PubMedClient,
        resolver: ConceptResolver,
        query_builder: QueryBuilder,
        state: AgentState,
    ):
        self.pubmed = pubmed
        self.resolver = resolver
        self.builder = query_builder
        self.state = state

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    def dispatch(self, name: str, args: dict) -> dict:
        """Route ``name(args)`` to the matching tool method and log it.

        Rejects identical repeated calls (same tool + same args) to
        force the agent to try a different strategy instead of
        burning iterations on the same query.
        """
        method = getattr(self, name, None)

        # Identical-call detection. ``finish`` is exempt — if the agent
        # reaches the finish condition twice it should be allowed to.
        fingerprint = _fingerprint(name, args or {})
        if (
            name != "finish"
            and method is not None
            and getattr(method, "_is_tool", False)
            and fingerprint in self.state.prior_tool_fingerprints
        ):
            result = {
                "error": (
                    "duplicate tool call — same tool with same arguments was "
                    "already executed earlier in this run. Try a different "
                    "strategy (different query, different slots, different direction)."
                )
            }
            self.state.log_tool_call(name, args or {}, result)
            return result

        if method is None or not getattr(method, "_is_tool", False):
            result = {"error": f"unknown tool: {name!r}"}
        else:
            try:
                result = method(**(args or {}))
            except TypeError as exc:
                result = {"error": f"bad arguments for {name}: {exc}"}
            except Exception as exc:
                logger.warning("Tool %s raised: %s", name, exc)
                result = {"error": f"{type(exc).__name__}: {exc}"}

        # Track fingerprint only after a successful dispatch.
        if method is not None and getattr(method, "_is_tool", False) and "error" not in result:
            self.state.prior_tool_fingerprints.add(fingerprint)

        self.state.log_tool_call(name, args or {}, result)
        return result

    # ------------------------------------------------------------------
    # Tool: pubmed_count
    # ------------------------------------------------------------------

    def pubmed_count(self, query: str) -> dict:
        count = self.pubmed.count(query)
        return {"count": count, "query": query}

    pubmed_count._is_tool = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Tool: pubmed_search
    # ------------------------------------------------------------------

    def pubmed_search(self, query: str, max_results: int = 40, rationale: str = "") -> dict:
        result = self.pubmed.esearch(query, max_results=max_results)
        details = (
            self.pubmed.fetch_details(result.pmids) if result.pmids else []
        )
        lightweight = [
            {
                "pmid": d.get("pmid"),
                "title": d.get("title"),
                "journal": d.get("journal"),
                "year": d.get("year"),
                "pub_types": d.get("pub_types", []),
            }
            for d in details
        ]
        new_pmids = [p for p in result.pmids if p not in self.state.accumulated_pmids]
        for pmid in new_pmids:
            self.state.pmid_source[pmid] = query
        self.state.accumulated_pmids.update(result.pmids)
        self.state.executed_queries.append(
            ExecutedQuery(
                query_string=query,
                rationale=rationale or "agent-initiated search",
                hit_count=result.total_count,
                papers_fetched=len(details),
                pmids=list(result.pmids),
            )
        )
        # Track productive queries — those that actually added new evidence.
        if len(new_pmids) >= PRODUCTIVE_QUERY_MIN_NEW:
            self.state.productive_queries += 1
        return {
            "pmids": result.pmids,
            "total_count": result.total_count,
            "new_pmids_added": len(new_pmids),
            "productive": len(new_pmids) >= PRODUCTIVE_QUERY_MIN_NEW,
            "productive_queries_so_far": self.state.productive_queries,
            "papers": lightweight,
        }

    pubmed_search._is_tool = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Tool: fetch_abstracts
    # ------------------------------------------------------------------

    def fetch_abstracts(self, pmids: list[str]) -> dict:
        records = self.pubmed.fetch_details(pmids)
        return {"papers": records}

    fetch_abstracts._is_tool = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Tool: plan_query
    # ------------------------------------------------------------------

    def plan_query(
        self,
        slots: Optional[list[str]] = None,
        include_filters: bool = True,
        min_year: Optional[int] = None,
        study_tiers: Optional[list[int]] = None,
    ) -> dict:
        """Build a PubMed query from selected slots (by state-key).

        ``slots`` names concepts in ``state.concepts`` to combine, e.g.
        ``["food", "outcome"]`` for a direct query or
        ``["component", "outcome"]`` for a mechanism query. Unknown slot
        names are silently skipped.

        ``study_tiers`` restricts results by publication type. See
        ``QueryBuilder.build_study_type_filter`` for the tier → pubtype
        mapping.
        """
        slots = list(slots or ["food", "outcome"])
        selected: dict[str, Concept] = {}
        for key in slots:
            if key in self.state.concepts:
                # Map "related_outcome" → "outcome" so the builder treats
                # the related concept as the outcome axis.
                canonical = "outcome" if key.startswith("related_outcome") else key
                if canonical == "outcome":
                    selected["outcome"] = self.state.concepts[key]
                else:
                    selected[canonical] = self.state.concepts[key]

        if "component" in selected and "outcome" in selected and "food" not in selected:
            query: Optional[str] = self.builder.build_mechanism_query(
                selected, include_filters=include_filters, min_year=min_year
            )
            strategy = "mechanism"
        else:
            try:
                query = self.builder.build_direct_query(
                    selected,
                    include_filters=include_filters,
                    min_year=min_year,
                )
            except ValueError as exc:
                return {"error": str(exc)}
            strategy = "direct"

        if query is None:
            return {"error": "could not build a query from the selected slots"}

        if study_tiers:
            filt = self.builder.build_study_type_filter(study_tiers)
            if filt:
                query = f"({query}) AND {filt}"

        estimated_cost = (
            "cheap" if len(selected) >= 2 else "moderate"
        )
        return {
            "query": query,
            "strategy": strategy,
            "slots_used": list(selected.keys()),
            "estimated_cost": estimated_cost,
            "rationale": (
                f"Built {strategy} query combining {sorted(selected.keys())}."
            ),
        }

    plan_query._is_tool = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Tool: get_related_concept
    # ------------------------------------------------------------------

    def get_related_concept(
        self,
        slot_name: str,
        direction: str = "sibling",
    ) -> dict:
        """Propose a *different* related concept and store it in state.

        Uses ``ConceptResolver.resolve_related`` which is explicitly
        designed to return a concept DIFFERENT from the original
        (validated via MeSH-overlap check, with one retry on tautology).

        Stores the result under ``state.concepts["related_<slot_name>"]``
        for a subsequent ``plan_query`` to reference. Capped at 2 calls
        per run.
        """
        existing_related_count = sum(
            1 for k in self.state.concepts if k.startswith("related_")
        )
        if existing_related_count >= 2:
            return {"error": "max 2 related concepts per run"}

        current = self.state.concepts.get(slot_name)
        if current is None:
            return {"error": f"no concept found for slot {slot_name!r}"}

        try:
            related = self.resolver.resolve_related(
                slot_name, current, direction=direction
            )
        except Exception as exc:
            return {"error": f"resolver failed: {exc}"}

        if not related.mesh_terms:
            # Tautology guard fired: resolver couldn't find anything different.
            self.state.retrieval_notes.append(
                f"get_related_concept({slot_name}, {direction}) "
                f"returned empty — resolver could not bridge to a distinct concept."
            )
            return {
                "error": "resolver returned no related concept distinct from the original",
                "concept": related.model_dump(),
            }

        key = f"related_{slot_name}"
        suffix = 2
        while key in self.state.concepts:
            key = f"related_{slot_name}_{suffix}"
            suffix += 1
        self.state.concepts[key] = related
        self.state.retrieval_notes.append(
            f"Added related concept {key}: "
            f"user_term={related.user_term!r} mesh={related.mesh_terms} "
            f"validated={related.validated}"
        )
        return {
            "stored_as": key,
            "concept": related.model_dump(),
        }

    get_related_concept._is_tool = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Tool: finish
    # ------------------------------------------------------------------

    def finish(self, rationale: str, chosen_pmids: Optional[list[str]] = None) -> dict:
        """Terminate the loop. Requires ≥ min_productive_to_finish productive queries.

        Exception: if the rationale explicitly signals exhaustion
        ("below_threshold", "no_productive_queries", "giving up"), we
        allow an early finish so the agent can bail out gracefully when
        the evidence base is genuinely thin.
        """
        bypass_tokens = ("below_threshold", "no_productive", "giving up", "exhaust")
        rationale_lower = (rationale or "").lower()
        allow_early = any(tok in rationale_lower for tok in bypass_tokens)

        if (
            not allow_early
            and self.state.productive_queries < self.state.min_productive_to_finish
        ):
            return {
                "error": (
                    f"cannot finish yet — only {self.state.productive_queries} "
                    f"productive queries executed (need "
                    f"{self.state.min_productive_to_finish}). A productive query "
                    f"is one that adds ≥{PRODUCTIVE_QUERY_MIN_NEW} new PMIDs. "
                    f"Try a different strategy (mechanism query, related outcome, "
                    f"relaxed filters). If the evidence genuinely doesn't exist, "
                    f"call finish with rationale containing 'below_threshold'."
                )
            }

        self.state.finished = True
        self.state.finish_rationale = rationale
        if chosen_pmids:
            for pmid in chosen_pmids:
                if pmid not in self.state.pmid_source:
                    self.state.pmid_source[pmid] = "agent-supplied"
                self.state.accumulated_pmids.add(pmid)
        return {
            "ok": True,
            "total_accumulated_pmids": len(self.state.accumulated_pmids),
            "productive_queries": self.state.productive_queries,
        }

    finish._is_tool = True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _relation_hint(direction: str) -> str:
    """Map a direction keyword to natural-language guidance for the resolver."""
    return {
        "broader": "broader sibling or parent concept",
        "mechanism": "underlying biological mechanism or causal process",
        "related": "closely related but not identical concept",
    }.get(direction, direction)


def _fingerprint(name: str, args: dict) -> str:
    """Canonical string representation of a tool call for dedup detection."""
    try:
        normalised = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        normalised = repr(sorted((str(k), str(v)) for k, v in args.items()))
    return f"{name}::{normalised}"


# ---------------------------------------------------------------------------
# Tool declarations (Gemini function-calling spec)
# ---------------------------------------------------------------------------

TOOL_DECLARATIONS: list[dict] = [
    {
        "name": "pubmed_count",
        "description": (
            "Return only the hit count for a PubMed query. Cheaper than "
            "pubmed_search; use this first to decide whether a query is "
            "worth running."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A PubMed Boolean query string."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "pubmed_search",
        "description": (
            "Execute a PubMed search and fetch lightweight metadata for "
            "the top results. Adds found PMIDs to the running set."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "description": "Max PMIDs to return; default 40."},
                "rationale": {"type": "string", "description": "Brief explanation for the audit log."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "plan_query",
        "description": (
            "Build a well-formed PubMed query by naming which resolved "
            "concepts to combine. Use 'food' and 'outcome' for the "
            "direct query; use 'component' and 'outcome' for the "
            "mechanism query; use 'related_outcome' (after get_related_concept) "
            "for semantic relaxation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slots": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concept slot keys to combine, e.g. ['food','outcome'].",
                },
                "include_filters": {"type": "boolean"},
                "min_year": {"type": "integer"},
                "study_tiers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Study-design tiers to include (1=SR/meta, 2=RCT, 3=cohort).",
                },
            },
            "required": ["slots"],
        },
    },
    {
        "name": "get_related_concept",
        "description": (
            "Propose a related concept for a slot (broader / mechanism / "
            "related) and store it under 'related_<slot_name>' in state. "
            "Capped at 2 calls per run."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slot_name": {"type": "string", "description": "One of 'food', 'outcome', 'component', 'population'."},
                "direction": {
                    "type": "string",
                    "enum": ["broader", "mechanism", "related"],
                },
            },
            "required": ["slot_name"],
        },
    },
    {
        "name": "fetch_abstracts",
        "description": "Fetch full abstracts for specific PMIDs. Use judiciously; expensive.",
        "parameters": {
            "type": "object",
            "properties": {
                "pmids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["pmids"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Terminate the loop. Call this when you have a diverse, relevant "
            "set of 15–40 papers spanning at least one tier-1 or tier-2 "
            "study design, OR when further queries are unproductive."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "rationale": {"type": "string"},
                "chosen_pmids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional final PMID selection.",
                },
            },
            "required": ["rationale"],
        },
    },
]
