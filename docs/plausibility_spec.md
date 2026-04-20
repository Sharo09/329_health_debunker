# Health Myth Debunker — Plausibility Classifier Implementation

## Project context

We are building a health-claim evaluation system scoped to food and
nutrition claims. The system takes a user's claim, asks clarifying
questions, retrieves evidence from PubMed and FDA CAERS, and produces
a verdict backed by deterministic rules over the evidence.

Current pipeline stations:

1. **Extraction** — LLM converts the raw claim into a partial PICO.
2. **Elicitation** — Asks the user clarifying questions to lock the PICO.
3. **Retrieval** — Queries PubMed and FDA CAERS using the locked PICO.
4. **Synthesis** — Applies rules over retrieved evidence.
5. **Presentation** — UI showing verdict and evidence.

This spec adds a new stage **between Stations 1 and 2**:

**Station 1.5 — Plausibility**

I am building Station 1.5 (Plausibility Classifier).

## What this stage does

Takes a `PartialPICO` from Station 1 and decides whether the claim is
worth investigating empirically before any retrieval or elicitation
happens. Some claims do not primarily require a literature review —
they can be evaluated on physiological or arithmetic grounds alone.
Running the full retrieval-and-synthesis pipeline on these claims
produces confident but wrong verdicts because the pipeline never
challenges the claim's basic premise.

The output is a `PlausibilityResult` — not a verdict, but a decision:
investigate this claim empirically, or don't, and if not, here's why.

## Motivating failure

The claim *"eating 100 apples per day is good for your health"*
currently returns **SUPPORTED** with high confidence. The pipeline
searches for "apples AND health," finds voluminous positive literature
on apples, and concludes in favor of the claim. The stated dose (100
per day) is extracted into the PICO, stored, and then ignored by every
downstream stage.

This failure generalizes:

- *"Is drinking 10 liters of water per day healthy?"*
- *"Does eating only raw meat cure diseases?"*
- *"Is 50,000 IU of vitamin D per day good?"*
- *"Does fasting for 30 days cure cancer?"*
- *"Can alkaline water reverse cancer?"*

Each has a pathological component (implausible dose, infeasible
duration, incoherent mechanism) that the current pipeline has no
pathway to notice.

## Design principles

- **Plausibility is not a verdict.** This stage answers "is this worth
  investigating?" not "is this true?" A claim can be implausible
  (pipeline skipped) or plausible (pipeline runs).
- **Determinism where testable, LLM where judgment matters.** Dose
  checks are arithmetic against curated thresholds — deterministic.
  Feasibility, mechanism, and frame checks require world knowledge —
  LLM-based. Never mix the two in a single decision.
- **Fail open, not closed.** When the stage cannot evaluate a claim
  (food not in reference table, dose not parseable), it passes the
  claim through rather than blocking. False blocks are worse than
  false passes; the user can always refuse to read the verdict.
- **Respect user agency.** When plausibility blocks, always offer an
  explicit "proceed anyway" path. Do not hard-refuse.
- **Transparent failures.** Every plausibility failure carries enough
  detail for the user to see why and contest it. No black-box refusals.

## The five failure modes

**F1 — Implausible dose or quantity.** The claim specifies a dose so
far above typical intake that no research exists, or known to cause
harm regardless of the food's properties.

> "100 apples per day." "10 liters of water." "50,000 IU vitamin D daily."

**F2 — Impossible or infeasible premise.** The claim describes a
behavior that cannot be sustained or executed as stated.

> "Eating only meat for a year." "Never drinking water." "Fasting for 30 days."

**F3 — Incoherent mechanism.** The claim describes a causal pathway
that contradicts basic physiology, chemistry, or biology.

> "Alkaline water reverses cancer by changing blood pH."
> "Eating raw onions draws out toxins through your feet."

**F4 — Category error.** The claim isn't in a scientific frame at
all, or uses scientific language to dress up a non-scientific idea.

> "Vibrations from crystals in food enhance immunity."
> "Negative energy in processed food."

**F5 — Claim is plausible; proceed.** None of F1–F4 apply. This is
the majority case. Send to the normal pipeline.

A claim can trigger multiple failures simultaneously. "Eat 100 apples
a day to cure cancer by balancing your chakras" triggers F1, F3, and
F4. The classifier returns all that apply.

## Interface contracts

### Input (from Station 1)

```python
# The flat PartialPICO from Station 1's to_flat().
class PartialPICO(BaseModel):
    raw_claim: str
    food: Optional[str]
    form: Optional[str]
    dose: Optional[str]           # free text — parsed in this stage
    frequency: Optional[str]
    population: Optional[str]
    component: Optional[str]
    outcome: Optional[str]
    ambiguous_slots: list[str]
```

### Output (to Station 2 or directly to Presentation)

```python
from typing import Literal, Optional
from pydantic import BaseModel

FailureType = Literal["F1_dose", "F2_feasibility", "F3_mechanism", "F4_frame"]
Severity = Literal["blocking", "warning"]


class PlausibilityFailure(BaseModel):
    failure_type: FailureType
    severity: Severity
    reasoning: str                     # 1–3 sentences, user-facing
    supporting_data: dict              # thresholds, sources, etc.


class PlausibilityResult(BaseModel):
    should_proceed_to_pipeline: bool
    failures: list[PlausibilityFailure]
    warnings: list[str]                # non-blocking concerns
    reasoning_summary: str             # one-paragraph user-facing summary
    dose_parse: Optional["ParsedDose"] = None   # echoed for audit
```

### Decision rules

| Failure            | Severity  | Action                              |
|--------------------|-----------|-------------------------------------|
| F1 harmful         | blocking  | do not proceed                      |
| F1 implausible     | warning   | proceed, lead output with warning   |
| F2 failure         | warning   | proceed, warn evidence may be thin  |
| F3 failure         | blocking  | do not proceed                      |
| F4 failure         | blocking  | do not proceed                      |
| None (F5)          | —         | proceed normally                    |

`should_proceed_to_pipeline = False` if *any* blocking failure is
present, else `True`.

## File structure

Create the following under `src/plausibility/`:

```
src/plausibility/
  __init__.py
  schemas.py                  # PlausibilityResult, PlausibilityFailure, ParsedDose
  reference_table.py          # loader for the quantitative reference data
  dose_checker.py             # F1: deterministic dose plausibility check
  mechanism_checker.py        # F2/F3/F4: LLM-based judgment checker
  plausibility_agent.py       # top-level orchestrator combining both

data/
  plausibility_reference.yaml # curated dose-threshold table
```

Tests:

```
tests/
  test_plausibility_schemas.py
  test_dose_checker.py
  test_reference_table.py
  test_mechanism_checker.py
  test_plausibility_agent.py
  fixtures/
    plausibility_test_claims.yaml    # 50–100 hand-labeled eval claims
```

## Task 1 — Schemas

Create `src/plausibility/schemas.py`.

```python
from typing import Literal, Optional
from pydantic import BaseModel

FailureType = Literal["F1_dose", "F2_feasibility", "F3_mechanism", "F4_frame"]
Severity = Literal["blocking", "warning"]


class ParsedDose(BaseModel):
    """Structured representation of the claim's stated dose."""
    numeric_value: Optional[float]
    unit: Optional[str]                # "apples", "IU", "mg", "liters", ...
    time_basis: Optional[str]          # "per day", "per week", None
    confidence: Literal["high", "medium", "low", "not_a_dose"]
    raw_source: str                    # original dose string from PICO


class PlausibilityFailure(BaseModel):
    failure_type: FailureType
    severity: Severity
    reasoning: str
    supporting_data: dict = {}


class PlausibilityResult(BaseModel):
    should_proceed_to_pipeline: bool
    failures: list[PlausibilityFailure] = []
    warnings: list[str] = []
    reasoning_summary: str = ""
    dose_parse: Optional[ParsedDose] = None
```

Tests: schema validation, `should_proceed_to_pipeline` derivation from
failures list (should be False iff any failure has severity=blocking).

## Task 2 — Quantitative reference table

Create `data/plausibility_reference.yaml`. Hand-curate 30 entries
minimum covering your 10 demo foods plus common supplements.

### Schema (per entry)

```yaml
<canonical_name>:
  unit: <unit of measurement, e.g. "whole apple", "IU per day", "g">
  typical_daily_low: <number>
  typical_daily_high: <number>
  implausibly_high: <number>   # no realistic population consumes this
  harmful_threshold: <number>  # tolerable upper intake or toxicity
  source: <citation>
  notes: <1–3 sentences>
  # Optional unit-aware aliases so dose parsing can normalise
  alternate_units:
    - unit: "g"
      ratio: 180    # 1 apple ≈ 180g
```

### Required entries for v1 (minimum)

Foods (your demo set):

- apple, coffee, turmeric, red meat, eggs, alcohol, dairy milk
- added sugar, artificial sweeteners

Supplements / nutrients:

- vitamin D, vitamin C, vitamin A, vitamin E
- iron, calcium, selenium
- omega-3 fatty acids
- caffeine (standalone, separate from coffee)

Edge cases with known toxicity at extreme intakes:

- water (hyponatremia threshold)
- Brazil nuts (selenium toxicity)
- licorice (glycyrrhizin — hypertension)
- tuna (mercury — weekly, not daily basis)

### Example entries

```yaml
apple:
  unit: whole apple
  typical_daily_low: 0
  typical_daily_high: 3
  implausibly_high: 10
  harmful_threshold: 20
  source: USDA Dietary Guidelines 2020-2025
  notes: >
    "An apple a day" is the folkloric norm. Above ~10/day, caloric and
    fiber load becomes problematic (>2,500 kcal, >150g fiber).
  alternate_units:
    - unit: g
      ratio: 180

vitamin_d:
  unit: IU per day
  typical_daily_low: 400
  typical_daily_high: 2000
  implausibly_high: 10000
  harmful_threshold: 4000
  source: NIH Office of Dietary Supplements — Vitamin D Fact Sheet
  notes: >
    UL is 4000 IU/day for adults 19+, 1000 IU/day for infants.
    Hypercalcemia documented at sustained intakes above ~10,000 IU/day.
  alternate_units:
    - unit: mcg
      ratio: 0.025    # 1 IU = 0.025 mcg vitamin D

water:
  unit: liters per day
  typical_daily_low: 1.5
  typical_daily_high: 3.5
  implausibly_high: 6
  harmful_threshold: 5
  source: Institute of Medicine DRIs for Water
  notes: >
    Harmful threshold depends heavily on intake rate, sodium status,
    and kidney function. Rule of thumb: >4L over a few hours risks
    hyponatremia regardless of daily volume.

caffeine:
  unit: mg per day
  typical_daily_low: 100
  typical_daily_high: 400
  implausibly_high: 800
  harmful_threshold: 1000
  source: FDA guidance + EFSA scientific opinion 2015
  notes: >
    FDA notes 400 mg/day as generally safe for healthy adults.
    Toxicity (arrhythmias, seizures) documented above ~1000 mg acute.
```

### Sources to populate from

- **NIH ODS Fact Sheets** (`ods.od.nih.gov/factsheets/list-all/`) for
  every vitamin and mineral — each has a tolerable upper intake
  (UL) table by age.
- **Institute of Medicine Dietary Reference Intakes** for
  macronutrients and water.
- **USDA Dietary Guidelines for Americans** for typical food ranges.
- **EFSA scientific opinions** for European equivalents / sanity checks.
- **FDA limits** for specific additives (caffeine, sweeteners).
- **Case reports and Cochrane reviews** for extreme-intake toxicity
  (Brazil nut selenium, licorice, etc.).

### Loader

Create `src/plausibility/reference_table.py`:

```python
from pathlib import Path
from typing import Optional
import yaml

from pydantic import BaseModel


class ReferenceEntry(BaseModel):
    canonical_name: str
    unit: str
    typical_daily_low: float
    typical_daily_high: float
    implausibly_high: float
    harmful_threshold: float
    source: str
    notes: str = ""
    alternate_units: list[dict] = []


class ReferenceTable:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or Path("data/plausibility_reference.yaml")
        self._entries: dict[str, ReferenceEntry] = self._load()

    def _load(self) -> dict[str, ReferenceEntry]:
        raw = yaml.safe_load(self.path.read_text())
        out = {}
        for name, body in raw.items():
            entry = ReferenceEntry(canonical_name=name, **body)
            out[name.lower()] = entry
        return out

    def lookup(self, food: str) -> Optional[ReferenceEntry]:
        if not food:
            return None
        return self._entries.get(food.strip().lower())
```

Tests: loader parses the YAML correctly, lookup is case-insensitive
and whitespace-tolerant, missing food returns None.

## Task 3 — Dose parser

Create `src/plausibility/dose_checker.py`.

### Parsing (LLM-assisted)

Use the existing `LLMClient` from `src/extraction/llm_client.py`. One
structured-output call with the schema below.

```python
DOSE_PARSE_SYSTEM_PROMPT = """\
Parse a dose expression from a health claim into a structured form.

You receive two inputs:
  raw_dose: a free-text dose string (may be empty or vague)
  food: the food or substance the dose refers to, for disambiguation

Return:
  numeric_value     the numeric quantity stated, or null if none
  unit              the unit as stated or naturally implied, or null
  time_basis        "per day", "per week", "per meal", "total", null
  confidence        "high"   — numeric + unit + time basis all clear
                    "medium" — two of three clear
                    "low"    — only a number, no unit or basis
                    "not_a_dose" — vague phrase like "a lot" / "some"
  raw_source        the original raw_dose string verbatim

Examples:

Input:  raw_dose="100 apples per day", food="apple"
Output: {
  "numeric_value": 100,
  "unit": "apple",
  "time_basis": "per day",
  "confidence": "high",
  "raw_source": "100 apples per day"
}

Input:  raw_dose="50000 IU", food="vitamin D"
Output: {
  "numeric_value": 50000,
  "unit": "IU",
  "time_basis": "per day",       # default assumption for supplements
  "confidence": "high",
  "raw_source": "50000 IU"
}

Input:  raw_dose="a lot of coffee", food="coffee"
Output: {
  "numeric_value": null,
  "unit": null,
  "time_basis": null,
  "confidence": "not_a_dose",
  "raw_source": "a lot of coffee"
}

Input:  raw_dose="2-3 cups/day", food="coffee"
Output: {
  "numeric_value": 2.5,
  "unit": "cup",
  "time_basis": "per day",
  "confidence": "high",
  "raw_source": "2-3 cups/day"
}

Return only the JSON object, no prose.
"""
```

Temperature 0. On `confidence == "not_a_dose"` or `numeric_value ==
None`, the checker returns no F1 failure (we can't evaluate an
unspecified dose).

### Unit normalisation

Given a parsed dose with a unit and the reference entry's `unit`, try
to normalise. If the parsed unit matches exactly, use directly. If
the entry has an `alternate_units` list, try to convert. If no match,
return None (unit mismatch — cannot evaluate).

```python
def normalize_to_reference_unit(
    parsed: ParsedDose, entry: ReferenceEntry
) -> Optional[float]:
    if parsed.numeric_value is None:
        return None
    value = parsed.numeric_value
    parsed_unit = (parsed.unit or "").lower().strip().rstrip("s")
    ref_unit = entry.unit.lower().strip().rstrip("s")
    if parsed_unit == ref_unit:
        return value
    # Try alternate units
    for alt in entry.alternate_units:
        alt_unit = alt["unit"].lower().strip().rstrip("s")
        if parsed_unit == alt_unit:
            return value * alt["ratio"]
    return None
```

### The F1 check

```python
def check_dose_plausibility(
    food: Optional[str],
    parsed_dose: ParsedDose,
    reference_table: ReferenceTable,
) -> Optional[PlausibilityFailure]:
    if not food or parsed_dose.confidence == "not_a_dose":
        return None

    entry = reference_table.lookup(food)
    if entry is None:
        return None   # cannot evaluate this food, skip F1

    value = normalize_to_reference_unit(parsed_dose, entry)
    if value is None:
        return None   # unit mismatch, skip F1

    if value >= entry.harmful_threshold:
        return PlausibilityFailure(
            failure_type="F1_dose",
            severity="blocking",
            reasoning=(
                f"The stated intake ({value} {entry.unit}) exceeds the "
                f"known harmful threshold ({entry.harmful_threshold} "
                f"{entry.unit}) per {entry.source}. At this level, "
                f"harm is documented regardless of the food's other "
                f"properties."
            ),
            supporting_data={
                "stated_value": value,
                "unit": entry.unit,
                "harmful_threshold": entry.harmful_threshold,
                "typical_range": [
                    entry.typical_daily_low,
                    entry.typical_daily_high,
                ],
                "source": entry.source,
                "notes": entry.notes,
            },
        )

    if value >= entry.implausibly_high:
        return PlausibilityFailure(
            failure_type="F1_dose",
            severity="warning",
            reasoning=(
                f"The stated intake ({value} {entry.unit}) is far above "
                f"typical consumption ({entry.typical_daily_low}–"
                f"{entry.typical_daily_high} {entry.unit}). No realistic "
                f"population consumes at this level, so no directly "
                f"applicable research exists; any retrieved evidence "
                f"will be on much smaller doses."
            ),
            supporting_data={
                "stated_value": value,
                "unit": entry.unit,
                "implausibly_high": entry.implausibly_high,
                "typical_range": [
                    entry.typical_daily_low,
                    entry.typical_daily_high,
                ],
                "source": entry.source,
            },
        )

    return None
```

Tests: for each reference entry, test doses below typical, at
typical, at implausible, and at harmful thresholds. Verify the right
severity fires at the right threshold. Test unit normalisation. Test
that missing food / unit / confidence returns None cleanly.

## Task 4 — Mechanism checker (F2, F3, F4)

Create `src/plausibility/mechanism_checker.py`.

One LLM call with structured output using the existing `LLMClient`.

### Schema

```python
from pydantic import BaseModel


class MechanismJudgment(BaseModel):
    is_feasible: bool
    feasibility_reasoning: str
    mechanism_is_coherent: bool
    mechanism_reasoning: str
    is_in_scientific_frame: bool
    frame_reasoning: str
```

### Prompt

```python
MECHANISM_SYSTEM_PROMPT = """\
You evaluate whether a health claim is worth investigating empirically.
You do NOT evaluate whether the claim is true — that requires literature
review. You evaluate three specific properties.

IMPORTANT: Dose plausibility is handled by a separate deterministic
checker. Do NOT comment on dose. Even if the claim mentions an extreme
dose, evaluate only whether the non-dose aspects of the claim are
feasible, coherent, and in a scientific frame.

1. FEASIBILITY — can a human actually do what the claim describes, for
   long enough and with enough people to have been studied?
     Feasible:   "eat an apple a day for a month"
     Feasible:   "take 1000mg vitamin C daily for 10 years"
     Borderline: "eat only meat for 6 months" (few people sustain this;
                 evidence will be sparse / case reports)
     Infeasible: "never drink water for a week" (death within ~3 days)

2. MECHANISM COHERENCE — is the proposed causal pathway consistent
   with basic physiology, chemistry, or biology?
     Coherent:   "vitamin C supports immune function"
     Incoherent: "alkaline water neutralises acid in cancer cells to
                 reverse cancer" (stomach acidifies all ingested water
                 immediately; blood pH is tightly homeostatic; cancer
                 biology is not primarily pH-driven)
     Incoherent: "eating raw onions pulls toxins out through the soles
                 of the feet"

3. SCIENTIFIC FRAME — is the claim in a frame where empirical testing
   is meaningful?
     In frame:     any claim with a definable intervention and outcome
     Out of frame: "crystal vibrations in food enhance chakra alignment"
                   (terms are undefined; no testable prediction)

For each property, return a boolean (true = the property holds, the
claim is worth investigating on this axis) and a 1–2 sentence reason.

Return only the JSON object, no prose.

EXAMPLES

Claim: "Does eating blueberries reduce oxidative stress?"
Output: {
  "is_feasible": true,
  "feasibility_reasoning": "Eating blueberries is a normal behavior, sustained at any quantity.",
  "mechanism_is_coherent": true,
  "mechanism_reasoning": "Blueberries contain anthocyanins and other antioxidants; 'reducing oxidative stress' is a well-established biological process.",
  "is_in_scientific_frame": true,
  "frame_reasoning": "Standard nutritional biochemistry claim."
}

Claim: "Can drinking alkaline water cure cancer?"
Output: {
  "is_feasible": true,
  "feasibility_reasoning": "Drinking alkaline water is feasible; it is commercially available.",
  "mechanism_is_coherent": false,
  "mechanism_reasoning": "The stomach acidifies ingested water within seconds; blood pH is tightly homeostatic and cannot be altered by diet in healthy people; cancer biology is not primarily pH-driven.",
  "is_in_scientific_frame": true,
  "frame_reasoning": "Uses biological language and is in principle testable, though the proposed mechanism is incoherent."
}

Claim: "Does the vibrational frequency of raw food improve spiritual immunity?"
Output: {
  "is_feasible": true,
  "feasibility_reasoning": "Eating raw food is feasible.",
  "mechanism_is_coherent": false,
  "mechanism_reasoning": "'Vibrational frequency of food' and 'spiritual immunity' are not defined biological concepts.",
  "is_in_scientific_frame": false,
  "frame_reasoning": "Mixes pseudoscientific terminology with non-empirical concepts; no testable predictions are implied."
}

Claim: "Does fasting for 40 days straight cure diabetes?"
Output: {
  "is_feasible": false,
  "feasibility_reasoning": "40-day fasts exceed documented safe limits; very few humans sustain this, so the empirical base is limited to case reports.",
  "mechanism_is_coherent": true,
  "mechanism_reasoning": "Caloric restriction and ketosis affect glucose metabolism; the causal question is coherent.",
  "is_in_scientific_frame": true,
  "frame_reasoning": "Standard empirical claim."
}

Claim: "Can eating only raw meat for six months reverse autoimmune disease?"
Output: {
  "is_feasible": false,
  "feasibility_reasoning": "Sustained raw-meat-only diets carry foodborne illness and nutrient-deficiency risk (no vitamin C); rarely maintained long enough to study; evidence is mostly anecdotal.",
  "mechanism_is_coherent": true,
  "mechanism_reasoning": "Elimination diets affecting gut microbiota and immune function is a coherent research direction.",
  "is_in_scientific_frame": true,
  "frame_reasoning": "Empirical frame."
}

Claim: "Does 2 cups of coffee per day reduce Parkinson's risk?"
Output: {
  "is_feasible": true,
  "feasibility_reasoning": "2 cups/day is typical consumption.",
  "mechanism_is_coherent": true,
  "mechanism_reasoning": "Caffeine's A2A receptor antagonism and associated neuroprotection is an established research direction.",
  "is_in_scientific_frame": true,
  "frame_reasoning": "Standard empirical claim."
}

Claim: "Does eating 100 apples a day prevent heart disease?"
Output: {
  "is_feasible": true,
  "feasibility_reasoning": "Non-dose aspects (eating apples, studying heart disease) are feasible in principle. Dose is handled elsewhere.",
  "mechanism_is_coherent": true,
  "mechanism_reasoning": "Apple fiber and polyphenols affecting cardiovascular risk is a coherent pathway at reasonable intakes.",
  "is_in_scientific_frame": true,
  "frame_reasoning": "Empirical claim."
}
"""
```

The last example is important — it shows the mechanism checker to
*ignore* extreme doses and only evaluate the non-dose aspects. The F1
checker catches the dose separately.

### The checker

```python
def check_mechanism(
    claim_text: str,
    llm_client,
) -> list[PlausibilityFailure]:
    messages = [
        {"role": "system", "content": MECHANISM_SYSTEM_PROMPT},
        {"role": "user", "content": f"Claim: {claim_text}\nOutput:"},
    ]
    judgment: MechanismJudgment = llm_client.extract(
        messages, MechanismJudgment
    )
    failures: list[PlausibilityFailure] = []
    if not judgment.is_feasible:
        failures.append(PlausibilityFailure(
            failure_type="F2_feasibility",
            severity="warning",
            reasoning=judgment.feasibility_reasoning,
            supporting_data={"raw_judgment": judgment.model_dump()},
        ))
    if not judgment.mechanism_is_coherent:
        failures.append(PlausibilityFailure(
            failure_type="F3_mechanism",
            severity="blocking",
            reasoning=judgment.mechanism_reasoning,
            supporting_data={"raw_judgment": judgment.model_dump()},
        ))
    if not judgment.is_in_scientific_frame:
        failures.append(PlausibilityFailure(
            failure_type="F4_frame",
            severity="blocking",
            reasoning=judgment.frame_reasoning,
            supporting_data={"raw_judgment": judgment.model_dump()},
        ))
    return failures
```

Tests: scripted LLM provider returning fixed judgments; verify the
failure list matches the judgment. At least one test for each of
F2, F3, F4 firing alone, two-at-once, all three at once, and none
firing.

## Task 5 — Orchestrator

Create `src/plausibility/plausibility_agent.py`.

```python
import os
from datetime import datetime, timezone
import json

from src.extraction.llm_client import LLMClient
from src.schemas import PartialPICO

from src.plausibility.schemas import (
    ParsedDose,
    PlausibilityFailure,
    PlausibilityResult,
)
from src.plausibility.reference_table import ReferenceTable
from src.plausibility.dose_checker import (
    check_dose_plausibility,
    DOSE_PARSE_SYSTEM_PROMPT,
)
from src.plausibility.mechanism_checker import (
    MECHANISM_SYSTEM_PROMPT,
    MechanismJudgment,
    check_mechanism,
)


DEFAULT_LOG_FILE = "logs/plausibility.jsonl"


class PlausibilityAgent:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        reference_table: ReferenceTable | None = None,
        log_file: str | None = None,
    ):
        self.llm = llm_client or LLMClient()
        self.reference_table = reference_table or ReferenceTable()
        self.log_file = log_file or DEFAULT_LOG_FILE

    def evaluate(self, pico: PartialPICO) -> PlausibilityResult:
        # F1: dose check
        parsed_dose = self._parse_dose(pico)
        f1 = None
        if parsed_dose is not None:
            f1 = check_dose_plausibility(
                pico.food, parsed_dose, self.reference_table
            )

        # F2/F3/F4: mechanism check
        f234 = check_mechanism(pico.raw_claim, self.llm)

        failures: list[PlausibilityFailure] = []
        if f1:
            failures.append(f1)
        failures.extend(f234)

        should_proceed = not any(
            f.severity == "blocking" for f in failures
        )
        warnings = [f.reasoning for f in failures if f.severity == "warning"]

        summary = self._summarise(failures, should_proceed)

        result = PlausibilityResult(
            should_proceed_to_pipeline=should_proceed,
            failures=failures,
            warnings=warnings,
            reasoning_summary=summary,
            dose_parse=parsed_dose,
        )

        self._log(pico, result)
        return result

    def _parse_dose(self, pico: PartialPICO) -> ParsedDose | None:
        if not pico.dose:
            return None
        messages = [
            {"role": "system", "content": DOSE_PARSE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"raw_dose: {pico.dose}\n"
                    f"food: {pico.food or 'unknown'}\n"
                    f"Output:"
                ),
            },
        ]
        try:
            return self.llm.extract(messages, ParsedDose)
        except Exception:
            # Dose parsing failed — fail open, skip F1.
            return None

    def _summarise(
        self,
        failures: list[PlausibilityFailure],
        should_proceed: bool,
    ) -> str:
        if not failures:
            return (
                "Claim is worth investigating empirically. "
                "Proceeding to elicitation and retrieval."
            )
        parts = []
        for f in failures:
            parts.append(f"{f.failure_type} ({f.severity}): {f.reasoning}")
        prefix = (
            "Plausibility issues detected — pipeline halted. "
            if not should_proceed
            else "Plausibility warnings — proceeding with caveats. "
        )
        return prefix + " ".join(parts)

    def _log(
        self, pico: PartialPICO, result: PlausibilityResult
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_claim": pico.raw_claim,
            "pico": pico.model_dump(),
            "result": result.model_dump(),
        }
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
```

Tests: end-to-end on scripted LLM + hand-crafted reference table.
Verify that:

- F5 (plausible claim) produces `should_proceed_to_pipeline=True`,
  empty failures.
- F1 harmful alone → blocking, pipeline halted.
- F1 implausible alone → warning, pipeline proceeds.
- F3 alone → blocking.
- F1 harmful + F3 → blocking, both failures present.
- Missing dose → F1 skipped, F2/F3/F4 still evaluated.
- Food not in reference table → F1 skipped cleanly.
- LLM failure on dose parse → falls through, F2/F3/F4 still run.

## Task 6 — Integration with existing pipeline

Modify the FastAPI backend (`backend/main.py`) to run plausibility
between `/api/extract` and `/api/finalize`.

### Option A: new endpoint

Add `POST /api/plausibility` that takes a `PartialPICO` and returns
a `PlausibilityResult`. The frontend calls it between extract and
finalize.

```python
@app.post("/api/plausibility", response_model=PlausibilityResult)
def check_plausibility(req: PlausibilityRequest):
    agent = PlausibilityAgent()
    pico = PartialPICO(**req.partial_pico)
    return agent.evaluate(pico)
```

### Option B: fold into /api/extract

Have `/api/extract` return the extraction result plus a plausibility
result. Simpler for the frontend but couples two concerns.

Use **Option A** — it lets the frontend show plausibility results
while elicitation happens, and keeps the stages independent.

### Frontend flow update

After `/api/extract` succeeds, before showing the clarifying
questions, call `/api/plausibility`. Three branches:

1. `should_proceed_to_pipeline == True` and no warnings → proceed to
   questions as now.
2. `should_proceed_to_pipeline == True` with warnings → show a
   non-blocking warning banner alongside the questions.
3. `should_proceed_to_pipeline == False` → render a dedicated
   "plausibility issue" panel with the specific failure details and
   two buttons: *Modify my claim* (go back to input) and *Search
   anyway* (continue to elicitation).

## Task 7 — UI for blocked claims

Dedicated React state in `App.tsx` for `stage === "plausibility_blocked"`.

Panel content:

```
⚠ PLAUSIBILITY ISSUE DETECTED

Your claim: "<raw_claim>"

We detected issues before beginning literature review:

<for each failure>
  <Failure type header + severity badge>
  <reasoning text>
  <relevant supporting_data, formatted>
</for>

Suggested alternatives:
  • <narrower or corrected versions of the claim, if available>

[ Modify my claim ]   [ Search anyway → ]
```

For the 100-apples example, the panel renders:

```
⚠ PLAUSIBILITY ISSUE DETECTED

Your claim: "Does eating 100 apples per day prevent heart disease?"

Dose issue (F1 — blocking):
  The stated intake (100 apple) exceeds the known harmful threshold
  (20 apple) per USDA Dietary Guidelines 2020-2025. At this level,
  harm is documented regardless of the food's other properties.

  Stated intake:       100 apples per day
  Typical adult intake: 0–3 apples per day
  Harmful threshold:   20 apples per day

What you could ask instead:
  • "Do 1–2 apples per day reduce cardiovascular risk?"  ← has
    substantial literature
  • "Is there a dose-response relationship between apple intake
    and heart disease?"

[ Modify my claim ]   [ Search anyway → ]
```

The "Search anyway" button routes through the pipeline normally but
carries a `plausibility_override=true` flag so the results page leads
with the original plausibility warning.

## Task 8 — Evaluation set

Create `tests/fixtures/plausibility_test_claims.yaml`. Hand-curate
50–100 claims, each labelled with expected output.

Schema:

```yaml
- claim: <raw claim text>
  expected_failures: [F1_dose, F2_feasibility, F3_mechanism, F4_frame]  # list
  expected_severities: [blocking, warning]                               # parallel list
  expected_should_proceed: <bool>
  reasoning_keywords: [<list of substrings expected in reasoning text>]
  notes: <why this claim is in the set>
```

Distribution target:

- 10–15 F1 claims (implausible/harmful doses) across different foods
- 10 F2 claims (infeasible durations, exclusive diets)
- 10 F3 claims (incoherent mechanisms)
- 5 F4 claims (category errors — rarer in practice)
- 20–30 F5 claims (plausible — should pass cleanly)
- 10–15 edge cases (borderline, multiple failures, ambiguous)

Example entries:

```yaml
- claim: "Does eating 100 apples per day prevent heart disease?"
  expected_failures: [F1_dose]
  expected_severities: [blocking]
  expected_should_proceed: false
  reasoning_keywords: [harmful, threshold, apple]
  notes: Canonical F1 blocker.

- claim: "Does eating 10 apples per day prevent heart disease?"
  expected_failures: [F1_dose]
  expected_severities: [warning]
  expected_should_proceed: true
  reasoning_keywords: [implausible, typical]
  notes: F1 warning — above typical but below harmful.

- claim: "Does eating an apple a day reduce heart disease risk?"
  expected_failures: []
  expected_severities: []
  expected_should_proceed: true
  reasoning_keywords: []
  notes: Canonical F5 — clean pass.

- claim: "Can drinking alkaline water cure cancer?"
  expected_failures: [F3_mechanism]
  expected_severities: [blocking]
  expected_should_proceed: false
  reasoning_keywords: [homeostatic, acid, pH]
  notes: Canonical F3 blocker.

- claim: "Does 2 cups of coffee per day reduce Parkinson's risk?"
  expected_failures: []
  expected_severities: []
  expected_should_proceed: true
  reasoning_keywords: []
  notes: F5 — well-within-dose, coherent, in frame.

- claim: "Does fasting for 40 days cure diabetes?"
  expected_failures: [F2_feasibility]
  expected_severities: [warning]
  expected_should_proceed: true
  reasoning_keywords: [sustained, safe]
  notes: F2 warning — rarely sustained, evidence thin, but not blocking.

- claim: "Do vibrations from raw food enhance chakra alignment?"
  expected_failures: [F3_mechanism, F4_frame]
  expected_severities: [blocking, blocking]
  expected_should_proceed: false
  reasoning_keywords: [undefined, non-empirical]
  notes: F3 + F4 combined.

- claim: "Does taking 50000 IU of vitamin D daily improve bone health?"
  expected_failures: [F1_dose]
  expected_severities: [blocking]
  expected_should_proceed: false
  reasoning_keywords: [upper intake, hypercalcemia]
  notes: F1 blocker on supplement UL.
```

### Evaluation runner

`tests/test_plausibility_eval.py`: loads the fixture, runs each claim
through `PlausibilityAgent` (with a real or mocked LLM), and reports
per-failure-type accuracy.

```python
def test_plausibility_eval():
    agent = PlausibilityAgent()
    with open("tests/fixtures/plausibility_test_claims.yaml") as fh:
        cases = yaml.safe_load(fh)
    results = []
    for case in cases:
        pico = _pico_from_claim(case["claim"])   # run extraction first
        result = agent.evaluate(pico)
        match = (
            result.should_proceed_to_pipeline
            == case["expected_should_proceed"]
        )
        results.append((case["claim"], match, result))
    accuracy = sum(1 for _, m, _ in results if m) / len(results)
    print(f"Plausibility accuracy: {accuracy:.1%}")
    assert accuracy >= 0.85   # v1 target
```

Target accuracy for v1: 85% overall, 95%+ on F1 (deterministic part).

## Task 9 — Logging

Every plausibility evaluation writes a JSONL record to
`logs/plausibility.jsonl` (handled by `PlausibilityAgent._log`).

Record shape:

```json
{
  "timestamp": "2026-04-20T10:15:32Z",
  "raw_claim": "Does eating 100 apples per day prevent heart disease?",
  "pico": { ... },
  "result": {
    "should_proceed_to_pipeline": false,
    "failures": [ ... ],
    "warnings": [ ... ],
    "reasoning_summary": "...",
    "dose_parse": { ... }
  }
}
```

This is audit trail for the report: which claims got blocked, why,
and whether the blocks were correct on the eval set.

## Non-goals for this stage

- Do not evaluate whether the claim is *true*. That is the job of
  retrieval + synthesis, downstream.
- Do not replace elicitation. Plausibility runs *before* elicitation;
  it gates whether elicitation happens at all.
- Do not re-implement dose parsing in Station 1. Station 1 extracts
  the dose as free text; this stage parses it into numbers. Keep
  concerns separate.
- Do not curate a reference table for every conceivable food. 30
  entries for v1; expand opportunistically when eval failures reveal
  gaps.
- Do not try to catch every pseudoscientific claim. F4 detection is
  best-effort — the LLM's judgment is good enough for common cases.
- Do not make plausibility "smart" via an agent loop. One LLM call
  for F2/F3/F4 + one deterministic check for F1 is sufficient; more
  complexity adds failure points without accuracy gains.

## Dependencies

- `pydantic >= 2.0` (already in project)
- `pyyaml` for reference table loading
- Existing `LLMClient` from `src/extraction/llm_client.py`
- Existing `PartialPICO` from `src/schemas.py`

No new external dependencies.

## Environment variables

Same as existing stages: `GEMINI_API_KEY` / `GOOGLE_API_KEY` for
the LLM client. No new variables.

## Deliverable

When done, I should be able to:

```python
from src.extraction import ClaimExtractor, LLMClient
from src.plausibility import PlausibilityAgent

llm = LLMClient()
extractor = ClaimExtractor(llm)
plausibility = PlausibilityAgent(llm)

pico = extractor.extract("Does eating 100 apples a day prevent heart disease?")
result = plausibility.evaluate(pico.to_flat())

assert result.should_proceed_to_pipeline is False
assert any(f.failure_type == "F1_dose" for f in result.failures)
assert any(f.severity == "blocking" for f in result.failures)
```

And for a plausible claim:

```python
pico = extractor.extract("Does an apple a day reduce heart disease risk?")
result = plausibility.evaluate(pico.to_flat())

assert result.should_proceed_to_pipeline is True
assert result.failures == []
```

And the eval set hits ≥85% agreement with hand-labeled expected
outputs.

## Start with Task 1

Please implement Task 1 (Schemas) first, including tests, and stop
so I can review before moving on.
