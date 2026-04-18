# Build Logbook

Running record of the Health Myth Debunker build, in the order work happened.

## Test-suite status

- **471 passed, 1 skipped** (the skipped test is the gated live-LLM integration check in `tests/test_extraction_integration.py`).
- Run: `python3 -m pytest tests/ -q`.

## Dependencies installed

- `pytest` (test runner)
- `pydantic >= 2.0` (schemas)
- `rapidfuzz` (fuzzy food-name matching)
- `google-generativeai` is **not** installed; the default Gemini provider in `LLMClient` lazy-imports it and raises a helpful `ImportError` if called without the SDK. Tests use an injected mock provider.

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

## Not yet built

- Station 3 (Retrieval — PubMed + FDA CAERS).
- Station 4 (Synthesis — deterministic rules over evidence).
- Station 5 (Presentation — Streamlit demo UI). `StreamlitAdapter` in Station 2 is a functional stub; Station 5 will likely refine the UX.
- Pipeline orchestrator wiring the four upstream stations together (the extraction → elicitation handoff is already drop-in compatible; the remaining wiring depends on Stations 3 and 4).
