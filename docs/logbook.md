# Build Logbook

Running record of the Health Myth Debunker build, in the order work happened.

## Test-suite status

- **711 passed, 2 skipped** (skipped: the two gated live-LLM tests in `tests/test_extraction_integration.py`, `tests/test_retrieval_live.py`, and the live-LLM branch of `tests/test_plausibility_eval.py`).
- Run: `python3 -m pytest tests/ -q`.
- TypeScript: `cd frontend && npx tsc --noEmit` clean.

## Dependencies installed

- `pytest` (test runner)
- `pydantic >= 2.0` (schemas)
- `rapidfuzz` (fuzzy food-name matching)
- `google-genai` (Gemini SDK)
- `requests`, `tenacity` (HTTP + retry)
- `diskcache` (Station 3 caching)
- `anthropic`, `fastapi` (Sharon's earlier Station 4 + later API server — Anthropic dep is dormant; we run on Gemini)
- `python-dotenv` (Sharon's backend wrapper)
- Node v20.18.1 + Vite + React + TypeScript (frontend)

**Note on Gemini SDK:** The project originally targeted `google-generativeai`, but Google deprecated that package and its structured-output path couldn't serialize pydantic schemas containing fields with defaults (`ValueError: Unknown field for Schema: default`). Swapped to the successor package `google-genai` during the first live-LLM test. Provider code in [src/extraction/llm_client.py](../src/extraction/llm_client.py) uses `google.genai.Client` and `GenerateContentConfig`; it picks up `GOOGLE_API_KEY` / `GEMINI_API_KEY` from the environment automatically.

---

## Station 2 — Elicitation (built first)

Takes a flat `PartialPICO` from Station 1, asks up to 3 clarifying questions via a pluggable UI adapter, and returns a `LockedPICO` ready for Station 3.

### Task 1 — Per-food priority table

Files:
- [src/elicitation/priority_table.py](../src/elicitation/priority_table.py)
- [tests/test_priority_table.py](../tests/test_priority_table.py)

Deliverables:
- `DIMENSION_PRIORITY` dict covering all 10 demo foods (coffee, turmeric, red meat, eggs, alcohol, vitamin D, intermittent fasting, artificial sweeteners, added sugar, dairy milk).
- `DEFAULT_PRIORITY = ["outcome", "population", "form"]` for unknown foods.
- `get_priority(food)` with case-insensitive + whitespace + fuzzy lookup (stdlib `difflib`, no external deps).
- Inline comments justify each food's priority ordering (e.g., alcohol leads with `dose` because effects are dose-dependent; turmeric leads with `form` because culinary vs. curcumin-extract is the dominant literature split).

### Task 2 — Question templates library

Files:
- [src/elicitation/question_templates.py](../src/elicitation/question_templates.py)
- [tests/test_question_templates.py](../tests/test_question_templates.py)

Deliverables:
- 30 specific `(slot, food)` templates — one per priority-table pair.
- 6 `GENERIC_TEMPLATES` (one per valid slot).
- `get_question(slot, food)` returns specific template if present, else generic.
- `FALLBACK_VALUE = "unknown"` sentinel — every template has a "Not sure" option mapped to this value.
- `QuestionTemplate` `TypedDict` gives static shape checks over the 4-field schema.

### Tasks 3 + 4 — Elicitation agent + UI adapter

Files:
- [src/schemas.py](../src/schemas.py) — `PartialPICO` (flat) and `LockedPICO`.
- [src/elicitation/errors.py](../src/elicitation/errors.py) — `ElicitationError`, `UnscopableClaimError`, `InsufficientElicitationError`.
- [src/elicitation/ui_adapter.py](../src/elicitation/ui_adapter.py) — `UIAdapter` ABC, `CLIAdapter` (injectable I/O for testing), `StreamlitAdapter` (lazy streamlit import).
- [src/elicitation/elicitor.py](../src/elicitation/elicitor.py) — `ElicitationAgent.elicit()` and `select_slots_to_ask()`.

Design decisions:
- **Fallback semantics.** User answering "Not sure" stores `"unknown"` as the slot value and appends the slot to `fallbacks_used`. The post-loop required-slot default only fires if `population` is still `None` (never asked, never pre-supplied). Outcome is hard-required — `None` raises `InsufficientElicitationError`, but `"unknown"` is allowed through so Station 3 can degrade to a broad search.
- **"Other" free-text detection.** `CLIAdapter` returns `(typed_text, typed_text)`; the elicitor flags any `internal_value` not in the template's `option_values` as free text, logs a warning, and records the slot in `other_slots` in the audit log.
- **Compound food.** Regex splits on ` and `, ` or `, `,`, `/` (case-insensitive) and keeps the first non-empty chunk. Warning appears in the logger and the JSONL record.
- **Audit log** at `logs/elicitation.jsonl` — one record per `elicit()` call. Path injectable for tests.

### Task 5 — Elicitor test suite

Files:
- [tests/fixtures.py](../tests/fixtures.py) — `MockUIAdapter` with pre-scripted answers.
- [tests/test_elicitor.py](../tests/test_elicitor.py) — 17 tests: happy path, partial-input skip, max-3 cap, "Not sure" fallback, no-food error, unknown food → default priority, population default, outcome-missing error, JSONL log fields, compound food, "Other" free text, and `select_slots_to_ask` ordering.

### Task 6 — End-to-end integration test (10 demo foods)

File:
- [tests/test_integration.py](../tests/test_integration.py)

Parametrized scenarios covering all 10 demo foods. Each scenario encodes mocked Station 1 input, scripted answers, expected locked PICO values, and expected derivable MeSH terms. A local `derive_mesh_terms()` helper proves the locked values would drive a sensible PubMed query.

**Design gap surfaced by the vitamin D scenario:** the priority `[form, dose, population]` never asks outcome. Station 1 must pre-extract outcome for vitamin D-style claims, or elicitation raises `InsufficientElicitationError`. The scenario now uses `"Does vitamin D prevent osteoporosis?"` with `outcome="bone_health"` pre-supplied. Flag this to Station 1's prompt if outcome isn't reliably extracted for vitamin D.

---

## Station 1 — Extraction (built second)

One LLM call that parses a raw user claim into a `PartialPICO` with per-slot confidence annotations and a scope gate. Everything else is validation, normalization, and error handling.

### Task 1 — Schemas

Files:
- [src/extraction/schemas.py](../src/extraction/schemas.py)
- [tests/test_extraction_schemas.py](../tests/test_extraction_schemas.py)

Deliverables:
- `SlotConfidence = Literal["explicit", "implied", "absent"]`.
- `SlotExtraction` with cross-field validators: `explicit` requires both `value` and `source_span`; `absent` requires `value is None`.
- Rich `PartialPICO` with seven `SlotExtraction` slots, `ambiguous_slots` auto-recomputed via `model_validator(mode="after")`, `is_food_claim` + `scope_rejection_reason` scope gate, and `notes` for compound-claim MVP.
- `VAGUE_VALUES = {"some", "a lot", "a little", ...}` — nominally non-null but too vague to act on.
- `compute_ambiguous_slots()` exposed as a standalone function so the extractor can re-run it after mutations.

**Key design decision:** `FlatPartialPICO` is an alias for Station 2's existing `src.schemas.PartialPICO`, not a parallel class. The two sides can't drift, and `to_flat()` returns an object Station 2 can consume directly with no adapter layer.

**Note on the spec's "implied + high-priority" clarification rule** (extraction_spec.md lines 70–74): per Task 1, `ambiguous_slots` only covers `absent` + vague values. The `implied + high-priority` check is Station 2's concern via `DIMENSION_PRIORITY`. Station 2's existing elicitor walks the priority table independently, so implied slots would still need a separate mechanism if you want them re-asked.

### Task 2 — Food normalizer

Files:
- [src/extraction/food_normalizer.py](../src/extraction/food_normalizer.py)
- [tests/test_food_normalizer.py](../tests/test_food_normalizer.py)

Deliverables:
- `KNOWN_FOODS` dict mapping canonical name → alias list for the 10 demo foods + `processed meat` (split out from `red meat` in the spec).
- `normalize_food(raw) -> (canonical_name, is_in_known_list)` using a three-stage strategy: exact alias → whole-phrase substring (min length 3) → `rapidfuzz.fuzz.ratio` at threshold 85.

**Key fix during build:** switched from `rapidfuzz.WRatio` to plain `fuzz.ratio` after WRatio's partial-match component scored unrelated strings like `"leggings"` vs `"egg"` at 90 — false positive. Plain ratio keeps typos at 85–93 and kills unrelated strings below 70. See comments in `_fuzzy_match`.

**Alias addition:** `curcumin` added to `turmeric`'s alias list so claims about "curcumin supplements" normalize to food=`turmeric`. The `component` slot still captures `curcumin` separately.

### Task 3 — Extraction prompt

Files:
- [src/extraction/prompt.py](../src/extraction/prompt.py)
- [tests/test_extraction_prompt.py](../tests/test_extraction_prompt.py)

Deliverables:
- `EXTRACTION_SYSTEM_PROMPT` covering: role, seven slots, three confidence levels, scope rule, vague-but-stated handling, compound-claim handling, output format, and an explicit `NEVER FABRICATE` section.
- Ten few-shot examples covering every case in the task breakdown: fully-specified, food+outcome only, vague claim, vague dose, explicit population, supplement vs. dietary, scope rejection (aspirin), compound claim, component (`caffeine`), implied population ("my grandma" → elderly).
- `build_extraction_prompt(claim)` returns a two-element messages list: system + user.
- Every few-shot example validates against `PartialPICO` (tests verify).

### Task 4 — LLM client wrapper

Files:
- [src/extraction/llm_client.py](../src/extraction/llm_client.py)
- [src/extraction/errors.py](../src/extraction/errors.py) — `ExtractionError`, `EmptyClaimError`.
- [tests/test_llm_client.py](../tests/test_llm_client.py)

Deliverables:
- `LLMClient(model="gemini-2.5-pro", temperature=0.0, log_file=None, provider=None)`.
- `.extract(messages, response_schema) -> BaseModel` with up to 3 retries on parse failures. On each retry, appends the failed response and a `RETRY_REMINDER` user message.
- Provider-agnostic: `provider` is a `Callable[[messages, schema, model, temp], str]`. Default is `_default_gemini_provider` with lazy `google.generativeai` import. Tests inject a scripted provider.
- Logs every attempt to `logs/extraction_llm.jsonl` with timestamp, model, temperature, attempt, messages, raw response, parsed result (or None), error (or None), and latency.
- Provider-level exceptions (network/transport) surface as `ExtractionError` immediately — no retry, per spec ("Retries up to 3 times on parse failures").

### Task 5 — Main extractor

Files:
- [src/extraction/extractor.py](../src/extraction/extractor.py)

Deliverables:
- `ClaimExtractor.extract(raw_claim)`:
  1. Empty / whitespace → `EmptyClaimError`.
  2. >500 chars → truncate + log warning to stderr + record `truncated: true` in the audit log.
  3. Build prompt, call LLM.
  4. If `is_food_claim`: normalize food via `normalize_food` — if canonical differs, rewrite `pico.food.value` but leave `source_span` (the verbatim claim substring) intact. Record the rewrite in the log.
  5. If not a food claim: scrub all slots to `absent` regardless of what the LLM returned; fill a default `scope_rejection_reason` if missing.
  6. Recompute `ambiguous_slots` deterministically — never trust the LLM here.
  7. Log the full record to `logs/extraction.jsonl`.
- Default log paths injectable via constructor; tests use `tmp_path`.

### Task 6 — Extractor tests

Files:
- [tests/fixtures.py](../tests/fixtures.py) — extended with `ExtractionTestCase` dataclass, `EXTRACTION_TEST_CASES` (10 labeled cases), helpers `_absent_slot`, `_explicit`, `_implied`, `_make_pico_dict`, and `mock_llm_provider`.
- [tests/test_extractor.py](../tests/test_extractor.py) — 25 tests: parametrized cases + guards (empty, whitespace, truncation) + `to_flat()` drop-wrappers + normalization override + canonical passthrough + unknown-food passthrough + ambiguous-slots recompute (even when LLM lies) + scope-rejection passthrough + scope-rejection slot-scrubbing + retry-then-success + log format checks.

### Task 7 — Live-LLM smoke test

File:
- [tests/test_extraction_integration.py](../tests/test_extraction_integration.py) — one test, skipped unless `RUN_LIVE_TESTS=1` is set. Verifies real-world extraction of `"Is turmeric good for inflammation?"` produces `food="turmeric"`, `is_food_claim=True`, and `"population" in ambiguous_slots`. **Do not run in CI.**

Default model is `gemini-2.5-flash` (override via `LIVE_LLM_MODEL=gemini-2.5-pro` on paid tier). `gemini-2.5-pro` has zero free-tier quota on AI Studio — the pro model is paid-only per current Google policy.

### Live run confirmation

Ran the live test and ad-hoc extractions against real Gemini on 2026-04-17 — all passed:

- Live integration test: passed in ~4s.
- Four ad-hoc claims exercised: fully-specified (coffee/pregnancy/miscarriage), supplement-vs-dietary (curcumin), scope rejection (aspirin), and typo normalization (tumeric). Gemini 2.5 Flash extracted all four correctly, including doing its own food-name corrections ("curcumin" → food=turmeric, "tumeric" → turmeric) — the normalizer now serves as a safety net rather than the primary path.

---

## Handoff contract between stations

```python
from src.extraction import ClaimExtractor, LLMClient
from src.elicitation import ElicitationAgent, CLIAdapter

client = LLMClient()  # defaults to gemini-2.5-pro, temp 0
extractor = ClaimExtractor(client)
agent = ElicitationAgent(CLIAdapter())

rich = extractor.extract("Is turmeric good for inflammation?")

if not rich.is_food_claim:
    # Surface rich.scope_rejection_reason in the UI; do NOT call elicit().
    print(rich.scope_rejection_reason)
else:
    locked = agent.elicit(rich.to_flat())
    print(locked.model_dump_json(indent=2))
```

`rich.to_flat()` returns an instance of `src.schemas.PartialPICO`, which is exactly what `ElicitationAgent.elicit` consumes. No adapter code needed between the stations.

## Full file inventory

Source:
- [src/__init__.py](../src/__init__.py)
- [src/schemas.py](../src/schemas.py)
- [src/elicitation/__init__.py](../src/elicitation/__init__.py)
- [src/elicitation/priority_table.py](../src/elicitation/priority_table.py)
- [src/elicitation/question_templates.py](../src/elicitation/question_templates.py)
- [src/elicitation/errors.py](../src/elicitation/errors.py)
- [src/elicitation/ui_adapter.py](../src/elicitation/ui_adapter.py)
- [src/elicitation/elicitor.py](../src/elicitation/elicitor.py)
- [src/extraction/__init__.py](../src/extraction/__init__.py)
- [src/extraction/schemas.py](../src/extraction/schemas.py)
- [src/extraction/food_normalizer.py](../src/extraction/food_normalizer.py)
- [src/extraction/prompt.py](../src/extraction/prompt.py)
- [src/extraction/errors.py](../src/extraction/errors.py)
- [src/extraction/llm_client.py](../src/extraction/llm_client.py)
- [src/extraction/extractor.py](../src/extraction/extractor.py)

Tests:
- [tests/__init__.py](../tests/__init__.py)
- [tests/fixtures.py](../tests/fixtures.py)
- [tests/test_priority_table.py](../tests/test_priority_table.py)
- [tests/test_question_templates.py](../tests/test_question_templates.py)
- [tests/test_elicitor.py](../tests/test_elicitor.py)
- [tests/test_integration.py](../tests/test_integration.py) (Station 2)
- [tests/test_extraction_schemas.py](../tests/test_extraction_schemas.py)
- [tests/test_food_normalizer.py](../tests/test_food_normalizer.py)
- [tests/test_extraction_prompt.py](../tests/test_extraction_prompt.py)
- [tests/test_llm_client.py](../tests/test_llm_client.py)
- [tests/test_extractor.py](../tests/test_extractor.py)
- [tests/test_extraction_integration.py](../tests/test_extraction_integration.py) (Station 1, live-gated)

---

## Station 3 — Retrieval (rebuilt per `docs/retrieval_spec.md`)

Sharon's first retrieval pass used hardcoded MeSH-string concatenation
(`"orange"[MeSH Terms]` — the colour, not the fruit). Full reconstruction:

| # | Task | Files | Tests |
|---|------|-------|-------|
| 1 | PubMed client | [pubmed_client.py](../src/retrieval/pubmed_client.py), [errors.py](../src/retrieval/errors.py), [schemas.py](../src/retrieval/schemas.py) | 26 |
| 2 | CAERS client (openFDA food/event) | [caers_client.py](../src/retrieval/caers_client.py) | 31 |
| 3 | **Concept resolver** — LLM-based MeSH lookup with PubMed-count validation | [concept_resolver.py](../src/retrieval/concept_resolver.py) | 19 |
| 4 | Concept-based query builder | [query_builder.py](../src/retrieval/query_builder.py) | 26 |
| 5 | Retrieval tools (the agent's tool catalogue) | [retrieval_tools.py](../src/retrieval/retrieval_tools.py), [agent_state.py](../src/retrieval/agent_state.py) | 23 |
| 6 | **Retrieval agent** — Gemini function-calling tool-use loop | [agent_llm.py](../src/retrieval/agent_llm.py), [retrieval_agent.py](../src/retrieval/retrieval_agent.py) | 12 |
| 7 | Parallel CAERS track (in retrieval agent) | (above) | (in #6) |
| 8 | Disk-backed cache | [cache.py](../src/retrieval/cache.py) | 4 |
| 9 | JSONL audit log (in retrieval agent) | (above) | (in #6) |
| 10 | Integration tests across 5 demo PICOs | [test_retrieval_integration.py](../tests/test_retrieval_integration.py) | 6 |
| 11 | Live smoke test (gated) | [test_retrieval_live.py](../tests/test_retrieval_live.py) | 1 skipped |

The orange/flu regression — `"orange"[MeSH]` returning the colour — is
fixed at the concept-resolver layer: the resolver explicitly maps
"orange" + food-context → `Citrus sinensis`, validates via PubMed hit
count, and surfaces the corrected MeSH downstream.

**Ratio of new vs. legacy:** when this work was done, the legacy
retrieval files coexisted with new ones (`retrieval_agent_new.py`,
`concept_query_builder.py`). They were collapsed in the cleanup pass
(below).

---

## Station 4 — Synthesis (rebuilt by Sharon, then expanded)

Sharon delivered an initial Anthropic-based version. Two follow-ups:

1. **SDK swap** — moved from Anthropic to Gemini for cost and to keep
   the project on a single LLM vendor. [src/synthesis/paper_scorer.py](../src/synthesis/paper_scorer.py).
2. **Bug-fix pass** triggered by a real run on "does orange prevent flu"
   that came back `SUPPORTED 80%` despite the literature being mixed.
   Four root-cause fixes:
   - **Bug 1 — extraction must infer component.** Added a
     "COMPONENT INFERENCE" section to the extraction prompt with a
     curated food→component table (orange→vitamin C, turmeric→curcumin,
     coffee→caffeine, red wine→resveratrol, etc.) and three new
     few-shot examples. [src/extraction/prompt.py](../src/extraction/prompt.py).
   - **Bug 2 — `get_related_concept` was returning tautologies.** The
     resolver got a dedicated `resolve_related()` method with its own
     prompt (explicit instructions and few-shots like
     *Influenza, Human → Common Cold*), plus a post-hoc validator that
     rejects results whose MeSH terms overlap >50% with the original
     and retries once. [src/retrieval/concept_resolver.py](../src/retrieval/concept_resolver.py).
   - **Bug 3 — agent was finishing after one query.** Added two guards:
     (i) `pubmed_search` now returns a `productive` boolean (≥5 new
     PMIDs) and a running `productive_queries_so_far` counter, and
     `finish` is rejected unless that counter is ≥2 (or the rationale
     contains a `below_threshold`-style bypass token); (ii) duplicate
     tool calls (same name + same args) are rejected by the dispatcher
     to force the agent to try a different strategy. [src/retrieval/agent_state.py](../src/retrieval/agent_state.py), [src/retrieval/retrieval_tools.py](../src/retrieval/retrieval_tools.py).
   - **Bug 4 — synthesis stance classifier was too loose.** Added a
     `not_applicable` stance to drop intervention-mismatch papers
     (essential oils, in-vitro flavanone studies, off-topic plant
     extracts) and rewrote both the scoring prompt and the verdict
     prompt to enforce intervention + outcome match before counting
     a paper as supports / contradicts / neutral. Added explicit
     confidence ceilings (~80% requires ≥1 SR/meta + ≥3 RCTs).
     [src/synthesis/paper_scorer.py](../src/synthesis/paper_scorer.py),
     [src/synthesis/schemas.py](../src/synthesis/schemas.py).

   After the four fixes, "does orange prevent flu" produces
   **INSUFFICIENT_EVIDENCE 50%** with 4 supporting + 3 contradicting
   + 8 neutral cited papers (Cochrane vitamin C reviews on both sides).
3. **Disabled Gemini "thinking" on score_papers** — the structured
   rubric scoring doesn't benefit from the reasoning pass; verdict
   keeps thinking on. ~30% latency cut on the scoring call.
4. **Synthesis logging** — every run writes a full audit record to
   `logs/synthesis.jsonl` with per-paper stances and the final verdict.

---

## Sharon's frontend integration

After Stations 1–4 worked end-to-end on the CLI, merged Sharon's
`sharon2` branch which contained:
- Vite/React/TypeScript frontend (`frontend/`)
- FastAPI backend wrapper (`backend/main.py`)
- `Dockerfile`, `.gitignore`

Cherry-picked only the additive files; rewrote `backend/main.py` imports
to point at the canonical `src/` (her `backend/src/` copies were stale
from before the retrieval rebuild). Added `python-dotenv` dep.

---

## Streaming UX

Split `/api/finalize` into two endpoints so the user sees retrieved
papers ~25s before the verdict appears:

- `/api/finalize` — Stations 1+2+3, returns `papers` + locked PICO
  summary (no `verdict`).
- `/api/synthesize` — Station 4 only, takes the `papers` from finalize,
  returns `verdict`.

Frontend ([App.tsx](../frontend/src/App.tsx)) calls them sequentially
in `handleRunAnalysis`. Retrieved papers + the user's claim + the
locked-PICO chips appear immediately after retrieval; a slate
"Synthesizing verdict from N papers… ~20–30 seconds" placeholder shows
where the verdict will land. When `/api/synthesize` returns, the
placeholder is replaced by the verdict banner + tabs.

Trade-off: total wall time unchanged, perceived wait roughly halved
because reading time and verdict-cooking time overlap.

---

## Dead-code cleanup

Once the new pipeline was live, removed:

| Removed | Replaced by |
|---|---|
| `src/retrieval/retrieval_agent.py` (Sharon's legacy) | renamed `retrieval_agent_new.py` → canonical name |
| `src/retrieval/query_builder.py` (Sharon's string-concat) | renamed `concept_query_builder.py` → canonical name |
| `tests/test_retrieval.py` (legacy tests) | replaced by `test_pubmed_client.py`, `test_query_builder.py`, `test_retrieval_agent.py` |
| `PubMedClient.search()` / `.fetch()` legacy shims | `.esearch()` / `.fetch_details()` |
| `Paper` dataclass + `RetrievalResult` dataclass | pydantic `RetrievedPaper` + `RetrievalResult` (V2 suffix dropped) |
| `LegacyRetrievalAgent` / `legacy_retrieve` aliases in `__init__.py` | gone |

Net: −2 modules, −2 dataclasses, −2 PubMedClient methods, −41 legacy
tests. Test count went 662 → 622, all passing.

---

## Adaptive (literature-informed) elicitation — Station 2 v2

Per a fresh design pass, replaced the static priority-table elicitor
with an **adaptive** agent that probes PubMed *before* asking the user
anything. New file [src/elicitation/adaptive_elicitor.py](../src/elicitation/adaptive_elicitor.py)
(static `ElicitationAgent` is unchanged — kept as a sibling for
fallbacks).

Workflow:
1. Resolve PICO concepts via the existing concept resolver.
2. Enumerate candidate evidence "slices" — combinations of slot
   overrides that materially change PubMed retrieval (food×outcome,
   component×outcome, food×related_outcome, component×related_outcome).
3. Probe each slice with `pubmed.count()` — cheap, ~200ms per call.
4. Rank slices by hit count.
5. If top/bottom ratio > 10× → ask the user, with hit counts visible
   in the option text ("Vitamin C for common cold (strong evidence,
   2,341+ papers)"). Options are sorted by evidence depth.
6. If ratio < 3× → silently pick the most-populous slice (the choice
   doesn't materially change retrieval).
7. Optionally probe + ask population on the chosen slice.

Budgets: max 15 PubMed `count` calls, max 3 user questions. Both hard caps.

The user's pick is encoded as an `overrides` dict (e.g.
`{"_use_component_focus": "true", "outcome": "common cold"}`) carried
through the option_value as JSON; the agent applies the overrides to
the LockedPICO.

Tests: [tests/test_adaptive_elicitor.py](../tests/test_adaptive_elicitor.py) (8 tests covering
high-impact ask, low-impact silent pick, insufficient-evidence
auto-pick, probe budget cap, fallback marking, audit-log integrity).

This is a methodological contribution worth flagging in the report:
**adaptive literature-informed elicitation routes users toward
productive queries based on what the literature actually contains,
rather than asking abstract questions about per-food priority slots.**

---

## Station 1.5 — Plausibility classifier (new stage between Extraction and Elicitation)

**Motivation.** "100 apples a day is good for your health" returned
**SUPPORTED / high confidence** because the pipeline searched "apples
AND health," found voluminous positive literature on apples, and
concluded in favor of the claim. The stated dose (100/day) was
extracted into the PICO and then ignored by every downstream stage.
Generalises to *10 L water/day*, *50,000 IU vitamin D*, *alkaline
water cures cancer*, *chakra crystals enhance immunity* — different
shapes of the same hole.

**Decision.** Add a new station between Extraction (Station 1) and
Elicitation (Station 2) whose job is **not** to verdict the claim,
but to **gate** whether the claim is worth investigating empirically
at all. Built per `docs/plausibility_spec.md`.

### Five failure modes

- **F1 — Implausible/harmful dose.** Deterministic arithmetic against
  a curated reference table. Warning at `implausibly_high`, blocking
  at `harmful_threshold`.
- **F2 — Infeasible premise.** LLM judgment (warning only — thin
  evidence is still evidence).
- **F3 — Incoherent mechanism.** LLM judgment (blocking).
- **F4 — Category error / non-scientific frame.** LLM judgment
  (blocking).
- **F5 — Plausible, proceed.** Majority case.

A claim can trigger multiple simultaneously (e.g. *"eat 100 apples a
day to cure cancer by balancing your chakras"* → F1 + F4).

### Design principles held

- **Fail open, not closed.** Every skip condition (missing food,
  unparseable dose, unknown unit, food not in table, LLM call fails)
  returns cleanly with **no failure** rather than blocking.
- **Determinism vs. judgment separated.** F1 is pure arithmetic; F2/F3/F4
  are one structured LLM call. The mechanism prompt is explicitly told
  to **ignore dose** — F1 remains the single source of truth for
  dose plausibility. This prevents double-counting and keeps the F1
  finding auditable.
- **Respect user agency.** The UI offers a *"Search anyway"* path on
  every block; it doesn't hard-refuse.
- **Transparent failures.** Each `PlausibilityFailure` carries
  `supporting_data` (stated value, thresholds, source citation) so
  the user can contest the block.

### Implementation

- [src/plausibility/schemas.py](../src/plausibility/schemas.py) —
  `ParsedDose`, `PlausibilityFailure`, `PlausibilityResult`. The
  model validator on `PlausibilityResult` **auto-derives**
  `should_proceed_to_pipeline = not any(f.severity == "blocking")`, so
  callers can't construct inconsistent states.
- [data/plausibility_reference.yaml](../data/plausibility_reference.yaml)
  — 22 hand-curated entries (10 demo foods + vitamins/minerals +
  edge cases: water, Brazil nut, licorice, tuna). Each row:
  `typical_daily_low/high`, `implausibly_high`, `harmful_threshold`,
  `source`, `notes`, optional `alternate_units` for normalisation.
- [src/plausibility/reference_table.py](../src/plausibility/reference_table.py)
  — loader. Case-insensitive, whitespace- and underscore-tolerant
  (`"red meat"` → `"red_meat"`). Missing food returns `None`.
- [src/plausibility/dose_checker.py](../src/plausibility/dose_checker.py)
  — two halves: `parse_dose()` (LLM, structured output to
  `ParsedDose`) and `check_dose_plausibility()` (pure arithmetic).
  `normalize_to_reference_unit()` handles alternate units (e.g.
  mcg→IU for vitamin D, g→apple by weight). Bare numbers with no
  unit are interpreted as the reference unit so *"100/day"* for
  apples still gates.
- [src/plausibility/mechanism_checker.py](../src/plausibility/mechanism_checker.py)
  — one LLM call returning a `MechanismJudgment` (three booleans +
  three reasons). Translates the judgment into zero-to-three
  `PlausibilityFailure` entries. Prompt includes eight calibrated
  few-shots — crucially, one shows the model ignoring an extreme
  dose so it leaves F1 to the deterministic checker.
- [src/plausibility/plausibility_agent.py](../src/plausibility/plausibility_agent.py)
  — orchestrator. Runs F1 and F2/F3/F4 independently, collects
  failures, derives a user-facing summary, logs every evaluation to
  `logs/plausibility.jsonl`.

### Integration with the pipeline

- Backend: new `POST /api/plausibility` endpoint in
  [backend/main.py](../backend/main.py), called between `/api/extract`
  and `/api/finalize`. Fails open — any endpoint error returns
  `should_proceed=true` with a warning, so a backend outage can never
  block a user.
- Frontend: [frontend/src/api.ts](../frontend/src/api.ts) gains
  `checkPlausibility()` and the `PlausibilityResponse` type.
  [frontend/src/App.tsx](../frontend/src/App.tsx) adds a new
  `plausibility_blocked` stage with a dedicated panel: red banner
  per failure, F1 failures render stated/typical/harmful values and
  the source citation, and the footer offers *"Modify my claim"* /
  *"Search anyway →"*. Warnings-only outcomes show a non-blocking
  yellow banner alongside the Station 2 questions. An override flag
  carries through to the results page so post-gate papers are
  labelled with the plausibility warning that led there.

### Tests

- `test_plausibility_schemas.py` — model validator + default
  derivation (7 tests).
- `test_plausibility_reference_table.py` — YAML load + lookup
  tolerance + ordering invariants (7 tests).
- `test_plausibility_dose_checker.py` — 21 tests covering
  parse-dose fail-open behaviour, unit normalisation (including
  mcg↔IU vitamin D), and every F1 threshold boundary.
- `test_plausibility_mechanism_checker.py` — scripted-LLM tests
  for each single-failure case, two-at-once, all-three-at-once
  (7 tests).
- `test_plausibility_agent.py` — 13 end-to-end tests: F5 clean
  pass, F1 blocking/warning alone, F3-only, F1+F3, missing dose,
  food-not-in-table, LLM failure (dose parse *and* mechanism) —
  both skip cleanly — plus summary-text and log-file assertions.
- `test_plausibility_eval.py` — hand-labelled evaluation set
  (Task 8, 60 claims) at
  [tests/fixtures/plausibility_test_claims.yaml](../tests/fixtures/plausibility_test_claims.yaml).
  Runs F1 deterministically against every row that supplies
  `food` + `dose` (25 cases, always on). A second live-LLM
  branch is gated on `RUN_LIVE_PLAUSIBILITY_EVAL=1`; spec
  target is ≥85% agreement overall.

### What this buys

- *"100 apples a day is good for your health"* — F1 blocks with
  `stated=100 apple, harmful_threshold=20`. Pipeline halts before
  retrieval ever runs.
- *"Does 1 apple a day reduce heart disease?"* — passes cleanly
  through F1-F4 and continues to elicitation.
- *"Can drinking alkaline water cure cancer?"* — F3 blocks on
  mechanism coherence before any PubMed round-trip.
- *"10 apples a day"* — F1 fires as a **warning**, pipeline still
  proceeds but the results page surfaces the warning banner.

The station lives in isolation: it's stateless between calls,
doesn't touch extraction output beyond reading the flat PICO, and
doesn't replace elicitation — it only gates whether elicitation
runs at all.

---

## File inventory (current)

Source:
- [src/__init__.py](../src/__init__.py)
- [src/schemas.py](../src/schemas.py)
- [src/elicitation/__init__.py](../src/elicitation/__init__.py)
- [src/elicitation/priority_table.py](../src/elicitation/priority_table.py)
- [src/elicitation/question_templates.py](../src/elicitation/question_templates.py)
- [src/elicitation/errors.py](../src/elicitation/errors.py)
- [src/elicitation/ui_adapter.py](../src/elicitation/ui_adapter.py)
- [src/elicitation/elicitor.py](../src/elicitation/elicitor.py) (static)
- [src/elicitation/adaptive_elicitor.py](../src/elicitation/adaptive_elicitor.py) (NEW — literature-informed)
- [src/extraction/](../src/extraction/) (unchanged)
- [src/plausibility/__init__.py](../src/plausibility/__init__.py) (NEW — Station 1.5)
- [src/plausibility/schemas.py](../src/plausibility/schemas.py)
- [src/plausibility/reference_table.py](../src/plausibility/reference_table.py)
- [src/plausibility/dose_checker.py](../src/plausibility/dose_checker.py)
- [src/plausibility/mechanism_checker.py](../src/plausibility/mechanism_checker.py)
- [src/plausibility/plausibility_agent.py](../src/plausibility/plausibility_agent.py)
- [data/plausibility_reference.yaml](../data/plausibility_reference.yaml)
- [src/retrieval/__init__.py](../src/retrieval/__init__.py)
- [src/retrieval/agent_llm.py](../src/retrieval/agent_llm.py)
- [src/retrieval/agent_state.py](../src/retrieval/agent_state.py)
- [src/retrieval/cache.py](../src/retrieval/cache.py)
- [src/retrieval/caers_client.py](../src/retrieval/caers_client.py)
- [src/retrieval/concept_resolver.py](../src/retrieval/concept_resolver.py)
- [src/retrieval/errors.py](../src/retrieval/errors.py)
- [src/retrieval/pubmed_client.py](../src/retrieval/pubmed_client.py)
- [src/retrieval/query_builder.py](../src/retrieval/query_builder.py)
- [src/retrieval/retrieval_agent.py](../src/retrieval/retrieval_agent.py)
- [src/retrieval/retrieval_tools.py](../src/retrieval/retrieval_tools.py)
- [src/retrieval/schemas.py](../src/retrieval/schemas.py)
- [src/retrieval/_gemini_retry.py](../src/retrieval/_gemini_retry.py)
- [src/synthesis/__init__.py](../src/synthesis/__init__.py)
- [src/synthesis/paper_scorer.py](../src/synthesis/paper_scorer.py)
- [src/synthesis/schemas.py](../src/synthesis/schemas.py)
- [backend/main.py](../backend/main.py) (FastAPI: `/api/extract`, `/api/plausibility`, `/api/finalize`, `/api/synthesize`, `/api/health`)
- [frontend/src/App.tsx](../frontend/src/App.tsx) + [frontend/src/api.ts](../frontend/src/api.ts)
- [demo.py](../demo.py) (CLI driver)

Logs (auto-generated, gitignored):
- `logs/extraction.jsonl`, `logs/extraction_llm.jsonl`
- `logs/elicitation.jsonl`
- `logs/plausibility.jsonl`
- `logs/retrieval.jsonl`
- `logs/synthesis.jsonl`
