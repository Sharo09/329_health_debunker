# Health Myth Debunker — Elicitation Stage Implementation

## Project context

We are building a health-claim evaluation system scoped to food and nutrition claims. The system takes a user's vague claim (e.g., "Is coffee bad for you?"), asks clarifying questions, retrieves evidence from PubMed and the FDA CAERS database, and produces a verdict backed by deterministic rules over the evidence.

The full pipeline has 5 stations:
1. **Extraction** — LLM converts the raw claim into a partial PICO.
2. **Elicitation** (this stage) — Asks the user clarifying questions to lock the PICO.
3. **Retrieval** — Queries PubMed and FDA CAERS using the locked PICO.
4. **Synthesis** — Applies deterministic rules over retrieved evidence.
5. **Presentation** — Streamlit UI showing the verdict and evidence.

I am building Station 2 (Elicitation).

## What this stage does

Takes a partial PICO from Station 1 (some slots filled, some ambiguous) and produces a fully-specified PICO by asking the user 2–3 clarifying questions. The clarifying questions are selected based on a per-food priority ordering of which ambiguities matter most for each specific food.

## Design principles

- **Ask as few questions as possible.** Max 3 questions total. Users hate interrogation.
- **Multiple-choice over free text.** Free text creates ambiguity we cannot route on. Always provide 3–6 options plus a fallback.
- **Per-food prioritization.** Not all ambiguities matter for all foods. Use a hard-coded priority table.
- **Options must correspond to distinct evidence populations.** If two answer options would retrieve the same PubMed results, collapse them.
- **Degrade gracefully.** If the user says "I don't know," fall back to a broad default and log it.

## Interface contracts

### Input (from Station 1)

```python
from pydantic import BaseModel
from typing import Optional, Literal

class PartialPICO(BaseModel):
    raw_claim: str                            # original user text
    food: Optional[str]                       # e.g. "coffee", "turmeric"
    form: Optional[str]                       # "dietary" | "supplement" | "extract" | None
    dose: Optional[str]                       # free text, e.g. "2-3 cups/day"
    frequency: Optional[str]                  # "daily" | "weekly" | "occasional" | None
    population: Optional[str]                 # "healthy adults" | "pregnant" | etc.
    component: Optional[str]                  # "caffeine" | "curcumin" | None
    outcome: Optional[str]                    # "heart disease" | "miscarriage" | etc.
    ambiguous_slots: list[str]                # slot names that are None or vague
```

### Output (to Station 3)

```python
class LockedPICO(PartialPICO):
    locked: bool = True
    conversation: list[tuple[str, str]]       # (question, answer) in order asked
    fallbacks_used: list[str]                 # slots where user said "don't know"
```

Note: `LockedPICO` inherits all fields from `PartialPICO`. After elicitation, all required slots should be filled.

### Required slots after locking

- `food` — must be non-null (if null, reject the claim as unscopeable).
- `outcome` — must be non-null.
- `population` — must be non-null.
- `form`, `dose`, `frequency`, `component` — may remain null if not prioritized for this food.

## File structure

Create the following files under `src/elicitation/`: