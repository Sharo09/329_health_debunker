# Health Myth Debunker — Extraction Stage Implementation

## Project context

We are building a health-claim evaluation system scoped to food and nutrition claims. The system takes a user's vague claim (e.g., "Is coffee bad for you?"), asks clarifying questions, retrieves evidence from PubMed and the FDA CAERS database, and produces a verdict backed by deterministic rules over the evidence.

The full pipeline has 5 stations:
1. **Extraction** (this stage) — LLM converts the raw claim into a partial PICO.
2. **Elicitation** — Asks the user clarifying questions to lock the PICO.
3. **Retrieval** — Queries PubMed and FDA CAERS using the locked PICO.
4. **Synthesis** — Applies deterministic rules over retrieved evidence.
5. **Presentation** — Streamlit UI showing the verdict and evidence.

I am building Station 1 (Extraction).

## What this stage does

Takes a raw user claim as a string. Uses an LLM with structured output to parse it into a `PartialPICO` object with six food-dimension slots filled in where possible. Also identifies which slots are ambiguous (unspecified or too vague to act on) and flags the claim as scopeable (food-related) or not.

This is the ONE LLM call in this stage. Everything else is validation, normalization, and error handling.

## Design principles

- **Slot confidence matters more than slot presence.** The LLM must distinguish "the claim explicitly says X," "the claim implies X," and "the claim is silent on X." Treating an inferred value the same as a stated value causes downstream misdirection.
- **Never fabricate.** If the claim says "coffee," the LLM must not fill in "2-3 cups/day" as the dose. A missing slot is fine; a hallucinated slot poisons retrieval.
- **Be strict about scope.** Our system only handles food and nutrition claims. Drug claims, supplement-adjacent medical claims (e.g., "does metformin prevent diabetes"), and non-health claims must be rejected early with a clear reason.
- **Normalize food names.** "Coffees," "a cup of joe," "caffeinated drink" → `"coffee"`. Normalization uses a known-food list; unknown foods are kept verbatim but flagged.
- **Temperature 0 for reproducibility.** We need deterministic output for audit.

## Interface contracts

### Input

Plain string from the user. No other context.

### Output (to Station 2)

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal

SlotConfidence = Literal["explicit", "implied", "absent"]

class SlotExtraction(BaseModel):
    """A single slot's extracted value plus how confident we are."""
    value: Optional[str] = None
    confidence: SlotConfidence = "absent"
    source_span: Optional[str] = None  # the substring of the claim this came from, if explicit

class PartialPICO(BaseModel):
    raw_claim: str

    # Six food dimensions. Each is a SlotExtraction so downstream can reason about confidence.
    food: SlotExtraction
    form: SlotExtraction            # "dietary" | "supplement" | "extract" | free-text
    dose: SlotExtraction            # free-text, e.g. "2-3 cups/day", "400mg"
    frequency: SlotExtraction       # "daily" | "weekly" | "occasional" | free-text
    population: SlotExtraction      # "healthy adults" | "pregnant" | free-text
    component: SlotExtraction       # "caffeine" | "curcumin" | ...
    outcome: SlotExtraction         # "heart disease" | "miscarriage" | ...

    # Computed convenience fields
    ambiguous_slots: list[str]      # slot names with confidence == "absent" or vague values

    # Scope gate
    is_food_claim: bool
    scope_rejection_reason: Optional[str] = None  # set if is_food_claim is False
```

**Note for Station 2:** the elicitation stage treats a slot as "needing clarification" when:
- `confidence == "absent"`, OR
- `confidence == "implied"` AND the slot is high-priority for this food

This is why we return confidence rather than collapsing to `Optional[str]`.

### Adapter for Station 2

Because Station 2's spec expects flat fields (not SlotExtraction objects), provide a `to_flat()` method on `PartialPICO` that returns a version with simple string fields plus an `ambiguous_slots` list. Both representations should exist; Station 2 can call `to_flat()` at its boundary.

```python
class FlatPartialPICO(BaseModel):
    raw_claim: str
    food: Optional[str]
    form: Optional[str]
    dose: Optional[str]
    frequency: Optional[str]
    population: Optional[str]
    component: Optional[str]
    outcome: Optional[str]
    ambiguous_slots: list[str]
```

## File structure

Create the following under `src/extraction/`: