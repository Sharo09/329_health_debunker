"""Station 3: Retrieval.

Public API — post-rebuild
-------------------------

The canonical high-level entry point is the new ``RetrievalAgent`` and
its supporting pieces:

    from src.retrieval import (
        RetrievalAgent,
        PubMedClient,
        CAERSClient,
        ConceptResolver,
        QueryBuilder,
        RetrievalCache,
    )

Sharon's legacy agent is still available under ``LegacyRetrievalAgent``
(alias of ``retrieval_agent.RetrievalAgent``) while the rest of the
pipeline (demo.py, Station 4) is migrated. It will be dropped once the
demo is wired to the new agent.
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
from src.retrieval.concept_query_builder import QueryBuilder
from src.retrieval.concept_resolver import ConceptResolver
from src.retrieval.pubmed_client import PubMedClient
from src.retrieval.retrieval_agent_new import RetrievalAgent
from src.retrieval.retrieval_tools import TOOL_DECLARATIONS, RetrievalTools
from src.retrieval.schemas import (
    CAERSReport,
    Concept,
    ESearchResult,
    ExecutedQueryModel,
    Paper,                     # legacy dataclass — used by Sharon's agent
    RetrievalResult,           # legacy dataclass
    RetrievalResultV2,
    RetrievedPaper,
)

# Legacy alias so existing imports keep working during the migration.
from src.retrieval.retrieval_agent import RetrievalAgent as LegacyRetrievalAgent
# Legacy convenience wrapper.
from src.retrieval.retrieval_agent import retrieve as legacy_retrieve

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
    "LegacyRetrievalAgent",
    "Paper",
    "PubMedClient",
    "QueryBuilder",
    "RetrievalAgent",
    "RetrievalCache",
    "RetrievalResult",
    "RetrievalResultV2",
    "RetrievalTools",
    "RetrievedPaper",
    "ScriptedAgentLLM",
    "Stop",
    "TOOL_DECLARATIONS",
    "ToolCall",
    "legacy_retrieve",
]
