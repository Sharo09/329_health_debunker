"""Station 3: Retrieval.

Public API
----------

    from src.retrieval import (
        RetrievalAgent,
        RetrievalResult,
        PubMedClient,
        CAERSClient,
        ConceptResolver,
        QueryBuilder,
        RetrievalCache,
    )

The retrieval pipeline is concept-based: the resolver translates
user-facing PICO terms into validated MeSH concepts before any
PubMed query is built. The agent is an LLM tool-use loop that
plans queries from those concepts.
"""

from src.retrieval.agent_llm import (
    AgentLLM,
    GeminiAgentLLM,
    ScriptedAgentLLM,
    Stop,
    ToolCall,
)
from src.retrieval.agent_state import AgentState, ExecutedQuery
from src.retrieval.cache import RetrievalCache
from src.retrieval.caers_client import CAERSClient
from src.retrieval.concept_resolver import ConceptResolver
from src.retrieval.pubmed_client import PubMedClient
from src.retrieval.query_builder import QueryBuilder
from src.retrieval.retrieval_agent import RetrievalAgent
from src.retrieval.retrieval_tools import TOOL_DECLARATIONS, RetrievalTools
from src.retrieval.schemas import (
    CAERSReport,
    Concept,
    ESearchResult,
    ExecutedQueryModel,
    RetrievalResult,
    RetrievedPaper,
)

__all__ = [
    "AgentLLM",
    "AgentState",
    "CAERSClient",
    "CAERSReport",
    "Concept",
    "ConceptResolver",
    "ESearchResult",
    "ExecutedQuery",
    "ExecutedQueryModel",
    "GeminiAgentLLM",
    "PubMedClient",
    "QueryBuilder",
    "RetrievalAgent",
    "RetrievalCache",
    "RetrievalResult",
    "RetrievedPaper",
    "RetrievalTools",
    "ScriptedAgentLLM",
    "Stop",
    "TOOL_DECLARATIONS",
    "ToolCall",
]
