# Health Myth Debunker — Elicitation Stage Patch: "Other" Free-Text Handling

## Context

This patch extends the existing elicitation stage (see `docs/elicitation_spec.md`). The base elicitation stage treated "Other" responses by storing the free text verbatim in the PICO slot and logging a warning. This is insufficient — downstream stages need to know which slots came from free text so they can apply different handling.

This patch adds structured tracking of free-text responses, input validation and trimming, and a clean interface contract with Station 3 (Retrieval) for free-text slot resolution.

**Important:** This patch deliberately does NOT add LLM calls to the elicitation stage. Elicitation remains rule-based and deterministic. All semantic interpretation of free-text inputs is delegated to Station 3's concept resolver. This preserves the project's architectural separation: elicitation is rules, retrieval is semantics.

## Design intent

The user selects "Other" when the multiple-choice options don't cover their situation. Their free-text response could be:

- A valid description of a less common category ("I have ulcerative colitis")
- A valid description in different phrasing ("my grandma" for population → elderly)
- A response in the wrong slot ("3 cups per day" in answer to a population question)
- Gibberish or empty ("asdfasdf", "idk")
- A response in a different language ("embarazada")

Elicitation handles the mechanical aspects (trimming, validation, empty-input fallback). The concept resolver in Station 3 handles the semantic aspects (mapping to MeSH terms, detecting wrong-slot responses, flagging low-confidence interpretations).

## Tasks

### Patch Task 1: Extend the `LockedPICO` schema

Update `src/elicitation/schemas.py` (or `src/schemas.py` if shared schemas live there).

Add a `free_text_slots` field to `LockedPICO`:

```python
class LockedPICO(FlatPartialPICO):
    locked: bool = True
    conversation: list[tuple[str, str]]
    fallbacks_used: list[str] = []
    free_text_slots: list[str] = []           # NEW: slot names where the user provided free text
    canonical_forms: dict[str, str] = {}      # NEW: populated by Station 3 after resolution
```

**Rationale:**
- `free_text_slots` tells Station 3 which slot values need the concept resolver's free-text handling path rather than the canonical-category path.
- `canonical_forms` is an empty dict at the end of elicitation. Station 3 populates it with normalized forms after the concept resolver runs. Station 5 uses these for display.

Update tests in `tests/test_elicitor.py` to verify:
- `free_text_slots` is empty when no "Other" responses were given.
- `free_text_slots` contains the slot name when the user selected "Other" for that slot.
- `canonical_forms` is always an empty dict at the end of elicitation (Station 3 fills it, not Station 2).

### Patch Task 2: Add input validation and trimming

Update `src/elicitation/elicitor.py` with a new helper method and integrate it into the elicitation loop.

```python
MAX_FREE_TEXT_LENGTH = 200
MIN_FREE_TEXT_LENGTH = 2

class InputValidationResult(BaseModel):
    is_valid: bool
    cleaned_text: Optional[str] = None
    rejection_reason: Optional[str] = None

def validate_and_clean_free_text(raw_input: str) -> InputValidationResult:
    """
    Deterministic validation of free-text input. No LLM calls.
    
    Rules:
    - Strip whitespace.
    - Reject if empty after stripping.
    - Reject if shorter than MIN_FREE_TEXT_LENGTH characters.
    - Truncate to MAX_FREE_TEXT_LENGTH characters if longer.
    - Reject if the input is pure punctuation or non-word characters.
    - Reject common non-answers: "idk", "i don't know", "none", "n/a", 
      "no", "nothing", "skip".
    """
    cleaned = raw_input.strip()
    
    if len(cleaned) == 0:
        return InputValidationResult(is_valid=False, 
            rejection_reason="empty input")
    
    if len(cleaned) < MIN_FREE_TEXT_LENGTH:
        return InputValidationResult(is_valid=False, 
            rejection_reason="too short")
    
    if len(cleaned) > MAX_FREE_TEXT_LENGTH:
        cleaned = cleaned[:MAX_FREE_TEXT_LENGTH]
    
    # Reject pure punctuation / no word characters
    if not any(c.isalnum() for c in cleaned):
        return InputValidationResult(is_valid=False, 
            rejection_reason="no alphanumeric content")
    
    # Reject common non-answers
    NON_ANSWERS = {
        "idk", "i dont know", "i don't know", "none", "n/a", "na",
        "no", "nothing", "skip", "unsure", "dunno", "?", "???"
    }
    if cleaned.lower() in NON_ANSWERS:
        return InputValidationResult(is_valid=False, 
            rejection_reason="non-answer input")
    
    return InputValidationResult(is_valid=True, cleaned_text=cleaned)
```

Tests for this function (in `tests/test_elicitor.py`):
- Empty string → invalid
- Whitespace-only → invalid  
- Single character → invalid
- Pure punctuation "!!!" → invalid
- "idk", "I don't know" case-insensitive → invalid
- Normal response "I have ulcerative colitis" → valid, cleaned
- Response with trailing whitespace → valid, cleaned and trimmed
- 300-char response → valid, truncated to 200
- Multi-language response "embarazada" → valid (validation is language-agnostic)

### Patch Task 3: Check if free text matches an existing option

Sometimes users type in free text that actually corresponds to an existing multiple-choice option ("adults" when "Healthy adults" was option 1). Catch this deterministically before treating it as free text.

Add to `elicitor.py`:

```python
def match_to_existing_option(user_input: str, 
                             options: list[str], 
                             option_values: list[str]) -> Optional[str]:
    """
    Check if the user's free-text input actually matches one of the 
    multiple-choice options via simple fuzzy match.
    
    Returns the corresponding option_value if matched, None otherwise.
    
    Uses rapidfuzz with a threshold of 80. This catches:
    - "adults" -> "Healthy adults"
    - "pregnant" -> "Pregnant or breastfeeding"
    - "kids" -> "Children"
    
    Does NOT catch distant semantic matches — those go to Station 3's 
    concept resolver.
    """
    from rapidfuzz import fuzz
    
    user_lower = user_input.lower().strip()
    
    best_score = 0
    best_value = None
    for option, value in zip(options, option_values):
        score = fuzz.partial_ratio(user_lower, option.lower())
        if score > best_score and score >= 80:
            best_score = score
            best_value = value
    
    return best_value
```

Tests:
- "adults" matches "Healthy adults" → returns "healthy_adults"
- "kid" matches "Children" → returns "children"
- "preg" matches "Pregnant or breastfeeding" → returns "pregnant"
- "ulcerative colitis" against `["Healthy adults", "Pregnant", "Children"]` → returns None (no match)
- Exact match "Healthy adults" → returns "healthy_adults"
- Case variants work

### Patch Task 4: Integrate into the elicitation loop

Update `ElicitationAgent.ask_slot()` (or whatever method currently presents questions) to use the new validation.

Pseudocode for the updated flow when the user selects "Other":

```python
def handle_other_response(self, slot_name: str, free_text: str, 
                          question_template: dict, pico: LockedPICO) -> str:
    """
    Process an "Other" response. Returns the slot value to store.
    """
    # Step 1: Validate and clean
    validation = validate_and_clean_free_text(free_text)
    if not validation.is_valid:
        # Fall back: pretend they selected "Not sure" if available, 
        # else use the slot's default fallback value
        pico.fallbacks_used.append(slot_name)
        return self._get_default_fallback(slot_name, question_template)
    
    cleaned = validation.cleaned_text
    
    # Step 2: Check if it matches an existing option
    matched_value = match_to_existing_option(
        cleaned,
        question_template["options"],
        question_template["option_values"],
    )
    if matched_value is not None:
        # Treat as if they selected that option — NOT marked as free_text
        return matched_value
    
    # Step 3: Genuine free text — mark it and store
    pico.free_text_slots.append(slot_name)
    return cleaned
```

Update the existing unit tests to cover:
- User types "Other" + valid free text → slot stores cleaned text, `free_text_slots` contains slot name.
- User types "Other" + empty input → falls back to default, `fallbacks_used` contains slot name, `free_text_slots` does NOT.
- User types "Other" + text matching an existing option → slot stores the canonical option value, `free_text_slots` does NOT contain slot name (we treat it as a match, not free text).
- User types "Other" + "idk" → falls back to default.
- User types "Other" + 500-char input → stored truncated to 200.

### Patch Task 5: Update UI adapter interface

The `UIAdapter.ask()` method previously returned `(display_label, internal_value)`. It needs a third return value indicating whether the response was a free-text "Other" entry.

Update the interface:

```python
class AskResponse(BaseModel):
    display_label: str          # what to show in the conversation log
    internal_value: str         # the value to store in PICO
    is_free_text: bool = False  # True if user selected "Other" and typed

class UIAdapter(ABC):
    @abstractmethod
    def ask(self, question: dict) -> AskResponse:
        ...
```

Update `CLIAdapter` and `StreamlitAdapter` to return `AskResponse` instead of a tuple.

For `CLIAdapter`:
- When the user enters the number corresponding to "Other (specify)," prompt for free text, return with `is_free_text=True`.
- Otherwise return with `is_free_text=False`.

For `StreamlitAdapter`:
- Use `st.radio` for the main options plus a conditional `st.text_input` that appears when the user selects "Other."
- Return with `is_free_text=True` when the text_input is used.

The `ElicitationAgent` uses `is_free_text` to route into `handle_other_response()` vs. treating the answer as a canonical option.

Update tests with a `MockUIAdapter` that supports scripted `AskResponse` sequences including free-text entries.

### Patch Task 6: Logging

Update the JSONL audit log entry to include free-text tracking:

```json
{
  "timestamp": "2026-04-18T15:20:00Z",
  "raw_claim": "is coffee bad for me",
  "input_partial_pico": {...},
  "slots_asked": ["outcome", "population"],
  "questions_and_answers": [
    {
      "slot": "outcome",
      "question": "Which health outcome are you asking about?",
      "answer_label": "Heart health / cardiovascular disease",
      "answer_value": "heart_health",
      "is_free_text": false
    },
    {
      "slot": "population",
      "question": "Who is this question about?",
      "answer_label": "I have ulcerative colitis",
      "answer_value": "I have ulcerative colitis",
      "is_free_text": true
    }
  ],
  "locked_pico": {...},
  "free_text_slots": ["population"],
  "fallbacks_used": []
}
```

The `is_free_text` flag per Q&A lets us audit later how often users actually use "Other" and whether the multiple-choice options should be expanded.

### Patch Task 7: Integration tests

Add tests in `tests/test_elicitor.py` that verify end-to-end behavior for the "Other" path:

1. **Happy-path "Other":** user types "I have ulcerative colitis" for population → `locked.population == "I have ulcerative colitis"`, `"population" in locked.free_text_slots`, `"population" not in locked.fallbacks_used`.

2. **"Other" with match to existing option:** user types "adults" for population → `locked.population == "healthy_adults"`, `"population" not in locked.free_text_slots` (matched option doesn't count as free text).

3. **"Other" with empty input:** falls back to default, `"population" in locked.fallbacks_used`, `"population" not in locked.free_text_slots`.

4. **"Other" with non-answer:** user types "idk" → same as empty input, falls back.

5. **"Other" on multiple slots:** user picks "Other" for both outcome and population, provides valid text for both → both appear in `free_text_slots`.

6. **Conversation log preserves free-text inputs verbatim:** the conversation list shows the user's actual typed text, not the cleaned/processed version, so the audit is truthful about what the user saw and said.

## Non-goals for this patch

- Do NOT add any LLM calls to elicitation. Semantic interpretation is Station 3's job.
- Do NOT attempt to detect "the user typed a different slot's value in this slot." That's Station 3's job via the concept resolver's cross-slot detection.
- Do NOT attempt language detection or translation. Pass through verbatim.
- Do NOT add a re-prompt loop ("your answer was unclear, please try again"). For now, fall back silently to the default. Re-prompting adds conversational complexity we don't need for the demo scope.

## Deliverables

After this patch, the following should hold:

```python
# Scenario: user types "I have ulcerative colitis" as "Other" for population
pico = elicitor.elicit(partial_pico_with_ambiguous_population)

assert pico.population == "I have ulcerative colitis"
assert "population" in pico.free_text_slots
assert "population" not in pico.fallbacks_used
assert pico.canonical_forms == {}  # Station 3 populates this later

# Scenario: user types "adults" (matches existing option)  
pico = elicitor.elicit(partial_pico_with_ambiguous_population)
assert pico.population == "healthy_adults"
assert "population" not in pico.free_text_slots

# Scenario: user types "idk"
pico = elicitor.elicit(partial_pico_with_ambiguous_population)  
assert pico.population == "healthy_adults"  # default fallback
assert "population" in pico.fallbacks_used
assert "population" not in pico.free_text_slots
```

## Start with Patch Task 1

Please implement Patch Task 1 (schema update) first, including tests, and stop so I can review before moving on.
