# Health Myth Debunker — Retrieval Stage Implementation

## Project context

We are building a health-claim evaluation system scoped to food and nutrition claims. The system takes a user's vague claim (e.g., "Does orange prevent flu?"), asks clarifying questions, retrieves evidence from PubMed and the FDA CAERS database, and produces a verdict backed by deterministic rules over the retrieved evidence.

The full pipeline has 5 stations:
1. **Extraction** — LLM converts the raw claim into a partial PICO. Also infers likely biologically active component (e.g., orange → vitamin C).
2. **Elicitation** — Asks the user clarifying questions to lock the PICO.
3. **Retrieval** (this stage) — Queries PubMed and FDA CAERS using the locked PICO.
4. **Synthesis** — Applies deterministic rules over retrieved evidence.
5. **Presentation** — Streamlit UI showing the verdict and evidence.

I am building Station 3 (Retrieval).

## What this stage does

Takes a `LockedPICO` from Station 2 and returns a set of relevant scientific papers (from PubMed) and safety signals (from FDA CAERS). This is the **one truly agentic component** of the pipeline — it uses an LLM with tool access to iteratively refine queries until it finds sufficient, relevant evidence.

The output is a `RetrievalResult` object handed to Station 4 (Synthesis).

## Critical context: the vocabulary mismatch problem

Our first retrieval implementation failed on simple claims because it constructed queries using the user's everyday language. Example of the broken behavior:

- User claim: "does orange prevent flu"
- Locked PICO: food="orange", outcome="flu"
- Broken query: `("orange"[MeSH Terms] OR "orange"[tiab]) AND ("flu"[MeSH Terms] OR "flu"[tiab])`
- Result: 6 irrelevant papers, verdict "insufficient evidence"

This was wrong for three reasons:

1. **`"orange"[MeSH Terms]` does not refer to the fruit.** The MeSH term for the fruit is `"Citrus sinensis"`. "Orange" as MeSH refers to the color.
2. **`"flu"[MeSH Terms]` does not exist.** The MeSH term is `"Influenza, Human"`. Medical literature uses "influenza," not "flu."
3. **The query ignored the biological mechanism.** Oranges "prevent flu" (if at all) via vitamin C's effects on respiratory infection. The relevant literature is indexed under "Ascorbic Acid" / "vitamin C" and "Common Cold" / "Upper Respiratory Infection" — none of which the query searched.

**The fix** is to introduce a concept-resolution layer that translates user-friendly PICO terms into PubMed's actual vocabulary, consider related biological mechanisms (the inferred component), and plan multiple complementary queries rather than one literal query. This is the core design of Station 3.

## Design principles

- **Concepts, not strings.** Every PICO slot is resolved into a `Concept` with multiple MeSH terms and title/abstract synonyms before being used in a query.
- **Plan multiple queries.** The agent considers the direct claim (food + outcome), the mechanism claim (component + outcome), and related outcome concepts (e.g., flu → upper respiratory infection). Results are unioned and deduplicated.
- **Validate before committing.** The agent uses cheap `pubmed_count` calls to check whether a query will be productive before fetching papers.
- **Semantic relaxation, not syntactic.** If results are sparse, try related concepts, not just looser Boolean structure.
- **Agentic, but budgeted.** The retrieval agent loops with tool use, but has a hard iteration cap and a token budget.
- **Determinism where possible.** LLM temperature is 0. Tool responses are cached. Two runs on the same PICO should produce the same paper set.
- **Parallel FDA CAERS track.** Runs alongside PubMed retrieval. Does not block. Failure in CAERS does not fail PubMed retrieval.

## Interface contracts

### Input (from Station 2)

A `LockedPICO` object with slots filled in:

```python
class LockedPICO(BaseModel):
    raw_claim: str
    food: str                             # required
    form: Optional[str]                   # "dietary" | "supplement" | "extract" | ...
    dose: Optional[str]
    frequency: Optional[str]
    population: str                       # required, may default to "healthy_adults"
    component: Optional[str]              # may be "implied" — USE THIS for mechanism queries
    outcome: str                          # required
    locked: bool = True
    conversation: list[tuple[str, str]]
    fallbacks_used: list[str]
```

### Output (to Station 4)

```python
class Paper(BaseModel):
    pmid: str
    title: str
    abstract: str
    pub_types: list[str]                  # raw from PubMed, used by Station 4 for design classification
    journal: str
    year: int
    authors: list[str]
    is_retracted: bool = False
    source_query: str                     # which query found this paper (for audit)
    
class CAERSReport(BaseModel):
    report_id: str
    date: str                             # ISO format
    product_name: str
    industry_name: str
    reactions: list[str]                  # preferred terms from CAERS
    outcomes: list[str]                   # e.g. "Hospitalization", "Death", "Other serious"

class RetrievalResult(BaseModel):
    locked_pico: LockedPICO               # echoed back for audit
    concept_resolutions: dict[str, "Concept"]  # what MeSH terms we resolved each slot to
    queries_executed: list[ExecutedQuery]      # full audit trail
    papers: list[Paper]                   # deduplicated, one entry per PMID
    caers_reports: list[CAERSReport]      # FDA safety signals, may be empty
    retrieval_notes: list[str]            # human-readable notes about what happened
    total_iterations: int
    budget_exhausted: bool
```

### The `Concept` and `ExecutedQuery` types

```python
class Concept(BaseModel):
    user_term: str                        # original PICO value, e.g. "orange"
    mesh_terms: list[str]                 # e.g. ["Citrus sinensis", "Citrus"]
    tiab_synonyms: list[str]              # e.g. ["orange", "oranges", "citrus fruit"]
    validated: bool                       # True if at least one MeSH term has PubMed hits
    notes: Optional[str] = None           # e.g. "user term 'orange' ambiguous; mapped to fruit"

class ExecutedQuery(BaseModel):
    query_string: str                     # the actual PubMed query string
    rationale: str                        # why the agent chose this query
    hit_count: int                        # from pubmed_count
    papers_fetched: int                   # may be less than hit_count due to limit
    pmids: list[str]
```

## File structure

```
src/retrieval/
  __init__.py
  schemas.py                  # Paper, CAERSReport, Concept, ExecutedQuery, RetrievalResult
  pubmed_client.py            # Thin wrapper over NCBI E-utilities
  caers_client.py             # Thin wrapper over openFDA food/event endpoint
  concept_resolver.py         # LLM-based MeSH translation with PubMed validation
  query_builder.py            # Concept sets -> PubMed Boolean query strings
  retrieval_agent.py          # Main agentic loop with tool use
  retrieval_tools.py          # Tools exposed to the LLM: pubmed_count, pubmed_search, etc.
  cache.py                    # Disk-based cache for PubMed and LLM responses
  tests/
    test_concept_resolver.py
    test_query_builder.py
    test_retrieval_agent.py
    test_pubmed_client.py
    test_caers_client.py
    fixtures.py
    live_smoke_test.py        # Gated on RUN_LIVE_TESTS env var
```

## Task 1: PubMed client

Create `pubmed_client.py` wrapping NCBI E-utilities. Three endpoints we need:

- `esearch.fcgi` — get PMIDs matching a query, with total count
- `esummary.fcgi` — get lightweight metadata for PMIDs (title, journal, pub types, year)
- `efetch.fcgi` — get abstracts for PMIDs

```python
class PubMedClient:
    def __init__(self, api_key: Optional[str] = None, cache: Optional[Cache] = None):
        """
        api_key: NCBI API key (optional but strongly recommended — 10 req/sec vs 3).
                 Read from PUBMED_API_KEY env var if not provided.
        cache: diskcache.Cache instance. All responses cached by URL+params.
        """
    
    def esearch(self, query: str, max_results: int = 100, 
                sort: str = "relevance") -> ESearchResult:
        """
        Execute a search. Returns PMIDs and total count.
        The total count may exceed len(pmids) if max_results was reached.
        """
    
    def count(self, query: str) -> int:
        """Shortcut for esearch with max_results=0, returns only the count. Cheap."""
    
    def fetch_details(self, pmids: list[str]) -> list[PaperMetadata]:
        """
        Fetch full details (including abstracts) for a list of PMIDs.
        Batches into groups of 200. Parses XML response.
        Returns Paper-compatible dicts with title, abstract, pub_types, journal, year.
        """
    
    def check_retractions(self, pmids: list[str]) -> set[str]:
        """
        Return the subset of PMIDs that are retracted.
        PubMed has a "Retracted Publication" publication type and retraction notices.
        """
```

### ESearchResult schema

```python
class ESearchResult(BaseModel):
    query: str
    pmids: list[str]
    total_count: int
    returned_count: int
```

### Requirements

- **Rate limiting.** Built-in rate limiter: 3 req/sec without API key, 10 req/sec with key. Use a token bucket or simple time-based lock.
- **Retries.** 3 retries with exponential backoff on 429 (rate limit) and 5xx errors. No retry on 4xx (client error).
- **Caching.** Every request cached by full URL + params. Cache key must include the query string verbatim.
- **XML parsing.** Use `xml.etree.ElementTree` for `efetch` responses. Abstract parsing must handle the nested `<AbstractText>` structure including labeled sections (BACKGROUND, METHODS, RESULTS, CONCLUSIONS) — concatenate these with newlines.
- **Error handling.** Network errors, malformed XML, empty results all raise typed exceptions (`PubMedNetworkError`, `PubMedParseError`) that the agent layer can catch gracefully.

### Tests

- Mock `requests.get` with canned responses for each endpoint.
- Verify rate limiter actually rate-limits (mock time, assert request intervals).
- Verify retry logic on 429 response.
- Verify abstract parsing with and without labeled sections.
- Verify caching: identical query hits cache on second call, no network request.
- Verify `check_retractions` correctly identifies retracted papers from pub_types.

## Task 2: CAERS client

Create `caers_client.py` wrapping the openFDA `/food/event` endpoint.

```python
class CAERSClient:
    BASE_URL = "https://api.fda.gov/food/event.json"
    
    def __init__(self, api_key: Optional[str] = None, cache: Optional[Cache] = None):
        """
        api_key: openFDA API key (optional, raises rate limit to 240/min from 40/min).
                 Read from OPENFDA_API_KEY env var if not provided.
        """
    
    def search_by_product(self, product_term: str, since_year: int = 2018, 
                          limit: int = 100) -> list[CAERSReport]:
        """
        Search for CAERS reports matching a product/ingredient term.
        Searches across products.name_brand and products.industry_name fields.
        """
    
    def count_by_reaction(self, product_term: str) -> dict[str, int]:
        """
        For a product, return a count of reports grouped by reaction preferred term.
        Useful for identifying the dominant reaction types (e.g. "Hepatic enzyme increased").
        """
```

### Critical notes

- CAERS data is inherently noisy. A CAERS report is an uncorroborated account by a consumer or clinician. Do NOT characterize CAERS reports as proof of harm. Station 4 and 5 are responsible for the appropriate language; Station 3 just returns the data.
- Product matching in CAERS is hard. Many reports use brand names ("Red Bull"), not ingredient names ("caffeine"). For a food like "coffee," try multiple search variants: the food name, the canonical scientific name, and an expanded brand-category if available.
- CAERS is FDA-only (US). For a non-US-focused system we'd need complementary sources; for this project US signals are sufficient and we note the limitation in the writeup.
- The `since_year` default of 2018 keeps reports recent enough to be relevant. Older reports are often duplicated in the database or refer to discontinued products.

### Tests

- Mock HTTP responses with canned CAERS JSON.
- Verify date filtering by `since_year`.
- Verify reaction grouping.
- Verify graceful handling of 404 (no results) — returns empty list, does not raise.

## Task 3: Concept resolver (this is the critical fix)

Create `concept_resolver.py`. This module takes PICO slot values in everyday language and produces `Concept` objects with validated MeSH terms and synonyms. It fixes the root cause of the orange-flu failure.

### Interface

```python
class ConceptResolver:
    def __init__(self, llm_client: LLMClient, pubmed_client: PubMedClient):
        ...
    
    def resolve(self, slot_name: str, user_term: str, 
                context: Optional[dict] = None) -> Concept:
        """
        Translate a user-facing term into a validated Concept.
        
        Args:
            slot_name: "food", "outcome", "component", "population"
            user_term: the value from the LockedPICO, e.g. "orange", "flu"
            context: optional dict with other slot values for disambiguation
                     e.g. {"food": "orange", "outcome": "flu"} when resolving "orange"
                     helps the LLM know we mean the fruit, not the color
        
        Returns:
            Concept with MeSH terms and synonyms, validated against PubMed.
        """
    
    def resolve_pico(self, pico: LockedPICO) -> dict[str, Concept]:
        """
        Resolve all relevant slots in a PICO to concepts.
        Returns a dict keyed by slot name.
        Runs slot resolutions in parallel via asyncio.
        """
```

### LLM prompt for concept resolution

The prompt must produce, given a user term and its slot type, a JSON structure like:

```json
{
  "primary_mesh": "Citrus sinensis",
  "alternative_mesh": ["Citrus"],
  "tiab_synonyms": ["orange", "oranges", "sweet orange", "citrus fruit"],
  "reasoning": "User term 'orange' in the context of a food claim refers to the fruit Citrus sinensis. Note: 'orange' as a standalone MeSH term refers to the color and is not relevant here."
}
```

Prompt requirements:

- Include the slot type ("food", "outcome", "population", "component") so the LLM knows the semantic context.
- Include the other PICO slot values as context for disambiguation.
- Explicitly instruct: *"'Primary_mesh' must be an actual MeSH Heading, not a free-text description. If the user term has no direct MeSH equivalent, return the closest MeSH Heading and note the mismatch in reasoning."*
- Include few-shot examples for each slot type covering:
  - **food**: orange → Citrus sinensis, turmeric → Curcuma, red meat → Red Meat (this one is a real MeSH term).
  - **outcome**: flu → Influenza, Human; miscarriage → Abortion, Spontaneous; heart attack → Myocardial Infarction; cancer → Neoplasms.
  - **component**: vitamin C → Ascorbic Acid, curcumin → Curcumin (it's a MeSH), caffeine → Caffeine.
  - **population**: pregnant women → Pregnancy (MeSH is the state, not the people); children → Child, Preschool or Adolescent depending on age context.

### Validation step

After the LLM returns, validate each proposed MeSH term against PubMed:

```python
def _validate_mesh(self, mesh_term: str) -> bool:
    """Run a minimal esearch with the MeSH term. Return True if hit count > 100."""
    count = self.pubmed.count(f'"{mesh_term}"[MeSH Terms]')
    return count > 100  # threshold for "real, productive MeSH term"
```

If `primary_mesh` fails validation, try each `alternative_mesh` until one validates, or fall back to tiab-only search.

### Critical behaviors this resolver must exhibit

For the orange-flu failure specifically, the resolver must produce:

- `resolve("food", "orange", context={"outcome": "flu"})` → `Concept(mesh_terms=["Citrus sinensis", "Citrus"], tiab_synonyms=["orange", "oranges", "citrus"], validated=True)`
- `resolve("outcome", "flu", context={"food": "orange"})` → `Concept(mesh_terms=["Influenza, Human"], tiab_synonyms=["influenza", "flu"], validated=True)`

And crucially, if the PICO has `component=None`, Station 1's extractor *should* have inferred `component="vitamin C"` for an orange-flu claim (this is addressed in extraction; retrieval assumes it's done). Resolve that to `Concept(mesh_terms=["Ascorbic Acid"], tiab_synonyms=["vitamin C", "ascorbic acid", "ascorbate"], validated=True)`.

### Tests

Write 10+ tests covering the major concept types from the few-shot examples. Mock the LLM with expected responses; mock PubMed count calls to return realistic numbers. Verify:

- Correct MeSH terms returned for each known case.
- Validation falls back to alternatives when primary fails.
- Context is correctly passed to the LLM for disambiguation.
- The specific orange-flu case: `food="orange"` + `outcome="flu"` → Citrus sinensis + Influenza, Human, both validated.

## Task 4: Query builder

Create `query_builder.py`. This takes a dict of resolved `Concept` objects and produces PubMed Boolean query strings. No more string concatenation with hardcoded MeSH tags.

### Interface

```python
class QueryBuilder:
    def build_direct_query(self, concepts: dict[str, Concept], 
                           include_filters: bool = True) -> str:
        """
        Build the primary query: food AND outcome, plus optional population filter.
        
        Example output for orange/flu:
        ((("Citrus sinensis"[MeSH Terms] OR "Citrus"[MeSH Terms]) 
          OR ("orange"[tiab] OR "oranges"[tiab] OR "citrus"[tiab]))
         AND 
         ((("Influenza, Human"[MeSH Terms])) 
          OR ("influenza"[tiab] OR "flu"[tiab]))
         AND humans[Filter]
         AND English[Language])
        """
    
    def build_mechanism_query(self, concepts: dict[str, Concept]) -> Optional[str]:
        """
        Build a mechanism-based query: component AND outcome.
        Returns None if no component was resolved.
        
        For orange/flu with component=vitamin C:
        (("Ascorbic Acid"[MeSH Terms]) OR ("vitamin C"[tiab] OR "ascorbic acid"[tiab]))
         AND (("Influenza, Human"[MeSH Terms]) OR ("influenza"[tiab] OR "flu"[tiab]))
         AND humans[Filter]
        
        This is the query that would have found the vitamin C / flu literature.
        """
    
    def build_related_outcome_query(self, concepts: dict[str, Concept], 
                                     related_outcome: Concept) -> str:
        """
        Build a query using a semantically related outcome instead of the exact one.
        Used for semantic relaxation when direct queries return too few results.
        
        For orange/flu, related_outcome might be "Common Cold" or "Upper Respiratory 
        Tract Infections".
        """
    
    def build_study_type_filter(self, tiers: list[int]) -> str:
        """
        Return a filter clause restricting to specific study design tiers.
        
        tiers = [1, 2] -> include meta-analyses, systematic reviews, RCTs.
        tiers = [1, 2, 3] -> add cohort studies, case-control.
        """
```

### Requirements

- **Proper Boolean grouping.** Every OR group is parenthesized; every AND joins parenthesized groups. No ambiguity.
- **Filter application.** `humans[Filter]` and `English[Language]` are applied by default but can be disabled for small-literature cases.
- **Date filter.** Support an optional `min_year` argument that adds `AND ("2000"[Date - Publication] : "3000"[Date - Publication])`.
- **Escape user content.** If any user-provided term contains special characters (brackets, quotes), escape them before inclusion.

### Tests

- Verify query for each of the 10 demo PICO fixtures matches expected output (snapshot tests).
- Verify `build_mechanism_query` returns None when component is missing.
- Verify query with empty tiab_synonyms list still produces a valid query using MeSH only.
- Verify the orange-flu direct query includes "Citrus sinensis" not "orange"[MeSH].

## Task 5: Retrieval tools for the agent

Create `retrieval_tools.py`. These are the callable tools the agent LLM has access to during the retrieval loop.

```python
class RetrievalTools:
    """Tools exposed to the retrieval agent LLM."""
    
    def __init__(self, pubmed: PubMedClient, query_builder: QueryBuilder, 
                 concepts: dict[str, Concept], state: "AgentState"):
        ...
    
    def pubmed_count(self, query: str) -> dict:
        """
        Cheap: execute an esearch with max_results=0 to get only the count.
        Used by the agent to decide whether a query will be productive before fetching.
        Returns {"count": int, "query": str}.
        """
    
    def pubmed_search(self, query: str, max_results: int = 40) -> dict:
        """
        Execute a search and fetch basic metadata for the top results.
        Returns {"pmids": [...], "total_count": int, "papers": [...]}.
        papers are lightweight summaries (title + journal + year), not full abstracts.
        """
    
    def fetch_abstracts(self, pmids: list[str]) -> dict:
        """
        Fetch full abstracts for specific PMIDs. This is the expensive operation
        the agent should use judiciously.
        Returns {"papers": [Paper, ...]}.
        """
    
    def get_related_concept(self, slot_name: str, current_concept: Concept, 
                            direction: str = "broader") -> dict:
        """
        Use the concept resolver to propose a related concept for semantic relaxation.
        direction: "broader" (more general), "mechanism" (underlying cause), 
                   "related" (sibling condition).
        
        For outcome="flu", direction="broader" -> "Upper Respiratory Tract Infections"
        For outcome="flu", direction="related" -> "Common Cold"
        """
    
    def finish(self, rationale: str, chosen_pmids: list[str]) -> dict:
        """
        Terminal tool. Agent calls this when it has enough evidence.
        """
```

### Notes

- Each tool call is logged to the agent's state for audit.
- Results from `pubmed_count` and `pubmed_search` are cached — the agent can call the same query twice without incurring two network requests.
- The agent does NOT construct raw query strings directly. It calls `pubmed_count` and `pubmed_search` with queries *built by the QueryBuilder*, which the agent parameterizes via the concept dict. This prevents the agent from reintroducing the string-concatenation bugs we're fixing.

### Actually, refine that last point

Give the agent a higher-level tool that abstracts query construction:

```python
def plan_query(self, 
               food_concept: Optional[str] = None,
               component_concept: Optional[str] = None,
               outcome_concept: Optional[str] = None,
               related_outcome_concept: Optional[str] = None,
               include_humans_filter: bool = True,
               min_year: Optional[int] = None) -> dict:
    """
    Plan and return a well-formed PubMed query without executing it.
    The agent picks which concepts to combine; the query builder handles
    the MeSH/tiab/Boolean syntax.
    
    Returns {"query": str, "estimated_cost": "cheap"|"moderate"|"expensive", 
             "rationale": str}.
    """
```

This keeps the agent focused on *semantic strategy* (which concepts to combine) rather than on *syntax* (how to write MeSH queries). The query builder is the source of truth for syntax.

## Task 6: The retrieval agent

Create `retrieval_agent.py`. This is the main agentic loop.

### Agent state

```python
class AgentState(BaseModel):
    locked_pico: LockedPICO
    concepts: dict[str, Concept]
    iterations: int = 0
    max_iterations: int = 8
    accumulated_pmids: set[str] = set()
    executed_queries: list[ExecutedQuery] = []
    tool_call_log: list[dict] = []
    budget_remaining_usd: float = 0.50  # soft token budget
    finished: bool = False
    finish_rationale: Optional[str] = None
```

### Agent loop

```python
class RetrievalAgent:
    def __init__(self, llm_client: LLMClient, tools: RetrievalTools, 
                 concept_resolver: ConceptResolver):
        ...
    
    def retrieve(self, pico: LockedPICO) -> RetrievalResult:
        # 1. Resolve all PICO concepts using the concept resolver
        # 2. Initialize agent state
        # 3. Run the agent loop with tool use until finish or budget exhausted
        # 4. Fetch full abstracts for the final PMID set (if not already fetched)
        # 5. Check retractions
        # 6. Package into RetrievalResult
```

### System prompt for the agent

The system prompt must convey:

1. The task: find a diverse, relevant set of papers for evaluating the claim.
2. The tools available and when to use each.
3. The target: 15-40 papers spanning multiple study types, from productive queries.
4. The strategies (in order of preference):
   - **Direct query** (food + outcome): try first.
   - **Mechanism query** (component + outcome): try always, especially if direct query has fewer than 20 results.
   - **Related outcome** (broader or sibling condition): try if first two strategies combined yield fewer than 15 papers.
   - **Relax filters**: drop the study-type restriction as a last resort.
5. **Do not relax to irrelevance.** If after all strategies the result set is still small and off-topic, it is better to return a small set with a note than to pad with irrelevant papers.
6. **Stopping criteria**:
   - 15+ papers from productive queries AND coverage of at least one tier-1 or tier-2 study design → finish.
   - 3 consecutive queries yielding 0 new PMIDs → finish.
   - `max_iterations` hit → finish with a "budget exhausted" note.
7. **Use `pubmed_count` before `pubmed_search`** to estimate productivity. Don't fetch 40 papers from a query returning 5000 hits; either narrow it or move on.

Include a few-shot trace showing the agent solving the orange-flu case: first a direct query that finds few results, then a mechanism query on vitamin C + influenza that finds the real literature, then a finish call.

### Tool-use integration

Use Gemini 3.1 Pro with function-calling mode. Each tool in `RetrievalTools` is registered as a function the LLM can invoke. The loop follows the standard pattern:

```
while not state.finished and state.iterations < state.max_iterations:
    response = llm.generate_with_tools(state_prompt, tools=tool_defs, 
                                        temperature=0)
    for tool_call in response.tool_calls:
        result = execute_tool(tool_call)
        state.tool_call_log.append({"call": tool_call, "result": result})
        state_prompt.append_observation(result)
    state.iterations += 1
```

### Budget and safety

- **Hard iteration cap: 8.** If the agent hasn't finished by then, stop and return what we have.
- **Token budget**: track total tokens consumed; if projected cost exceeds `budget_remaining_usd`, force-finish.
- **Tool call cap**: max 20 tool calls per retrieve(). Prevents runaway loops.
- **No recursive concept resolution.** `get_related_concept` is called at most twice per agent run.

### Post-loop processing

After the agent finishes (or is forced to stop):
1. Consolidate `accumulated_pmids` (deduplicate).
2. If fewer than 10 PMIDs have full abstracts, fetch them.
3. Check retractions; mark papers accordingly (do not remove — Station 4 decides how to handle).
4. Attach `source_query` to each paper (which executed query first surfaced it).
5. Build `RetrievalResult`.

### Tests

- **Unit tests** with mocked LLM and mocked tools. Verify:
  - Agent terminates within iteration cap.
  - Agent calls `pubmed_count` before `pubmed_search` in typical paths.
  - Agent invokes `get_related_concept` when direct queries are unproductive.
  - Agent calls `finish` when stopping criteria are met.
  - Tool call logging captures every call.
  
- **Integration-style test** with real query builder + concept resolver but mocked PubMed/LLM. Verify the orange-flu case:
  - Direct query for orange + flu returns few results.
  - Agent invokes mechanism query for vitamin C + flu.
  - Mechanism query returns many results.
  - Agent finishes with ~20-30 PMIDs including vitamin C / common cold literature.

## Task 7: Parallel CAERS track

In `retrieval_agent.py`, add a parallel CAERS retrieval that runs alongside the PubMed agent loop:

```python
async def retrieve_caers_parallel(pico: LockedPICO, caers_client: CAERSClient) -> list[CAERSReport]:
    """
    Search CAERS for the food term. Runs in parallel with the PubMed agent.
    Returns reports or empty list on any failure.
    """
    try:
        reports = await asyncio.to_thread(
            caers_client.search_by_product, pico.food, since_year=2018, limit=100
        )
        return reports
    except Exception as e:
        logger.warning(f"CAERS retrieval failed: {e}")
        return []
```

In the main `retrieve()` method:

```python
async def retrieve_async(self, pico: LockedPICO) -> RetrievalResult:
    pubmed_task = asyncio.create_task(self._run_pubmed_agent(pico))
    caers_task = asyncio.create_task(retrieve_caers_parallel(pico, self.caers))
    papers, concepts, queries = await pubmed_task
    caers_reports = await caers_task
    return RetrievalResult(...)
```

CAERS does not use an agent — it's a direct lookup. The "intelligence" is in matching the PICO's food term to the CAERS product field, which is handled by the client. If the food is well-known to have no CAERS signal (e.g., "oranges," "eggs"), the result will be empty; that's expected.

## Task 8: Caching layer

Create `cache.py` using `diskcache`:

```python
class RetrievalCache:
    def __init__(self, path: str = ".cache/retrieval"):
        self.pubmed = Cache(f"{path}/pubmed", size_limit=500_000_000)  # 500MB
        self.llm = Cache(f"{path}/llm", size_limit=200_000_000)         # 200MB
        self.caers = Cache(f"{path}/caers", size_limit=100_000_000)     # 100MB
```

Cache invalidation strategy:

- Caches are keyed on the full input (query string + API params for PubMed; messages + model + temperature for LLM).
- No TTL. Results are stable within the demo timeframe. For production we'd add a 30-day TTL.
- Cache is opt-in: pass `use_cache=False` to bypass (useful during debugging).

## Task 9: Logging and audit trail

Every retrieval run writes a JSONL record to `logs/retrieval.jsonl`:

```json
{
  "timestamp": "2026-04-18T14:32:01Z",
  "raw_claim": "does orange prevent flu",
  "locked_pico": {...},
  "concepts_resolved": {...},
  "agent_iterations": 4,
  "tool_calls": [
    {"tool": "pubmed_count", "query": "...", "result": {"count": 6}},
    {"tool": "get_related_concept", "args": {...}, "result": {...}},
    {"tool": "pubmed_count", "query": "...", "result": {"count": 342}},
    {"tool": "pubmed_search", "query": "...", "result": {...}},
    {"tool": "finish", "rationale": "..."}
  ],
  "final_paper_count": 28,
  "caers_report_count": 0,
  "budget_exhausted": false,
  "total_latency_ms": 4230,
  "total_llm_tokens": 3120
}
```

This is our audit trail. It's what we show the professor when asked "why did the system find these papers?"

## Task 10: Integration tests on demo claims

In `tests/test_retrieval_agent.py`, include integration tests for each of the 10 demo PICOs. These use real query builder + real concept resolver, with PubMed and LLM mocked with realistic fixture responses.

Key claims to test:

1. **orange/flu** — expected behavior: direct query returns few results, mechanism query (vitamin C + influenza) returns ~30, finish with good coverage.
2. **turmeric/inflammation** — expected: component is curcumin; evidence base is large but mostly supplement dose. Papers returned should include both dietary and supplement studies (Station 4 flags the mismatch).
3. **coffee/pregnancy** — expected: direct query on caffeine + pregnancy outcomes is productive. No need for related_outcome expansion.
4. **red meat/cancer** — expected: direct query productive. Retrieves IARC-related literature.
5. **vitamin D/COVID** — expected: recent literature; ensure min_year handling works.

For each, assert:
- The concept for food resolves to the correct MeSH term (e.g., orange → Citrus sinensis, not the color).
- The concept for outcome resolves to the correct MeSH term.
- The mechanism query is constructed when component is present.
- Papers returned are non-empty and relevant (check by PMID against a known-good list in the fixture).

## Task 11: Live smoke test

One live end-to-end test gated behind `RUN_LIVE_TESTS=1`. Runs the orange-flu claim through the full pipeline (mocking only LLM for determinism, hitting real PubMed) and asserts that ≥15 relevant papers are retrieved, including at least one systematic review or RCT.

## Non-goals for this stage

- Do not classify study design. That is Station 4's job.
- Do not extract sample size, population details, or stance from abstracts. Station 4.
- Do not filter for "relevance" in a semantic sense. Return what the queries found; Station 4 decides what to keep.
- Do not rank papers by quality. Station 4.
- Do not generate the final verdict. Station 4.

The boundary is: Station 3 finds what the literature contains; Station 4 evaluates it.

## Dependencies

- `pydantic >= 2.0`
- `requests` for HTTP
- `diskcache` for caching
- `asyncio` for parallelism (stdlib)
- `pytest`, `pytest-asyncio`, `pytest-mock`
- `google-generativeai` for Gemini
- `xml.etree.ElementTree` for PubMed XML (stdlib)

## Environment variables

- `GEMINI_API_KEY` — required
- `PUBMED_API_KEY` — optional, raises rate limit from 3 to 10 req/sec. Get one at ncbi.nlm.nih.gov/account (free).
- `OPENFDA_API_KEY` — optional, raises rate limit from 40/min to 240/min. Get one at open.fda.gov/apis/authentication.
- `RUN_LIVE_TESTS` — set to `1` to enable live smoke test.

## Deliverables

When done, I should be able to:

```python
from src.retrieval import RetrievalAgent, LLMClient, PubMedClient, CAERSClient, ConceptResolver, QueryBuilder

llm = LLMClient(model="gemini-3.1-pro-preview", temperature=0.0)
pubmed = PubMedClient()
caers = CAERSClient()
resolver = ConceptResolver(llm, pubmed)
builder = QueryBuilder()
tools = RetrievalTools(pubmed, builder)
agent = RetrievalAgent(llm, tools, resolver, caers)

# From Station 2:
locked_pico = LockedPICO(
    raw_claim="does orange prevent flu",
    food="orange",
    outcome="flu",
    population="healthy_adults",
    component="vitamin C",  # inferred by Station 1
    form="dietary",         # from elicitation
    ...
)

result = await agent.retrieve_async(locked_pico)

assert len(result.papers) >= 15
assert "Ascorbic Acid" in result.concept_resolutions["component"].mesh_terms
assert "Citrus sinensis" in result.concept_resolutions["food"].mesh_terms
assert any("vitamin C" in q.query_string for q in result.queries_executed)
```

And the orange-flu case, which previously returned 6 irrelevant papers and "insufficient evidence," now returns 15-40 relevant papers including vitamin C and respiratory infection literature.

## Start with Task 1

Please implement Task 1 (PubMed client) first, including tests, and stop so I can review before moving on.
