# Health Myth Debunker — Elicitation Patch B

## What this patch does

Right now, several elicitation slots (`dose`, `form`, `frequency`,
`population`) are collected from the user and then ignored. Extraction
parses them, elicitation asks about them, the `LockedPICO` stores them
— and then retrieval and synthesis don't condition on them. The
questions feel like theater because, downstream, they are.

This patch adds the missing layer: **stratified post-retrieval
synthesis.** Instead of narrowing the query on these slots (which
risks empty result slices), we retrieve broadly on `food + outcome`,
then use the stratifier slots to **partition, weight, and annotate**
the retrieved papers in the synthesis and results UI.

After this patch:

- Every question elicitation asks has a concrete downstream consumer.
- The user sees their specific `dose` / `form` / `frequency` /
  `population` reflected in how the results page organises the
  evidence — not buried in a log nobody reads.
- Generalisation warnings ("your question is about dietary turmeric
  but 90% of the retrieved evidence is on supplements at 50x the
  dose") become first-class output rather than a missing feature.

## Project context

This patch sits on top of:

- `docs/extraction_spec.md` (Station 1)
- `docs/elicitation_spec.md` (Station 2)
- `docs/retrieval_spec.md` (Station 3)
- `docs/plausibility_spec.md` (Station 1.5)

It modifies Stations 2, 3, 4, and 5. No new station. The pipeline
order is unchanged:

```
Extraction → Plausibility → Elicitation → Retrieval → Synthesis → Presentation
```

What changes is the **role** of elicitation slots and the
**behaviour** of synthesis.

## The core design principle

Every PICO slot falls into exactly one of three roles:

### Role 1 — Pre-retrieval (narrows the query)

Used when the slot value materially changes *which* papers are
retrieved, and where narrowing to the user's value is safe (the
resulting slice has substantial evidence).

Slots in this role: `outcome`, `component`.

These go into the PubMed query as MeSH/tiab clauses — exactly as
today.

### Role 2 — Post-retrieval stratifier (partitions results)

Used when the slot value matters for *interpreting* which retrieved
papers apply to the user, but narrowing the query risks emptying the
slice. Retrieve broadly, then partition.

Slots in this role: `dose`, `form`, `frequency`, `population`.

These do NOT go into the PubMed query. Instead, synthesis extracts
each paper's studied value for the slot (e.g., "this paper studied
curcumin supplement at 500 mg/day"), then assigns each paper to a
*stratum* based on proximity to the user's stated value.

### Role 3 — Fixed by extraction (not elicited)

Used when extraction confidently determined the value. Don't re-ask.

Slots in this role: whichever slots extraction returned with
`confidence=="explicit"`.

---

Slot assignments for v1:

| Slot        | Role              | Rationale                                        |
|-------------|-------------------|--------------------------------------------------|
| food        | Pre-retrieval     | Always in query. Never elicited.                 |
| outcome     | Pre-retrieval     | Changes which body of literature is searched.    |
| component   | Pre-retrieval     | Enables mechanism queries; narrows meaningfully. |
| dose        | Stratifier        | Numeric, stratifies cleanly; narrowing risky.    |
| form        | Stratifier        | Dietary/supplement split is the key case.        |
| frequency   | Stratifier        | Similar to dose.                                 |
| population  | Stratifier        | Broader literature, narrower applicability.      |

The priority table in `priority_table.py` should be updated to reflect
this split (see Task 2).

## Interface contracts

### New schemas (synthesis)

Add to `src/synthesis/schemas.py`:

```python
from typing import Literal, Optional
from pydantic import BaseModel

StratumMatch = Literal[
    "matches",         # paper's value matches user's stated value
    "higher",          # paper studied more than user asked about
    "lower",           # paper studied less than user asked about
    "different",       # categorically different (e.g., form mismatch)
    "unreported",      # paper doesn't state its value for this slot
    "not_applicable",  # user didn't state a value for this slot
]


class PaperStratification(BaseModel):
    """How a single paper relates to the user's stated PICO values."""
    paper_id: str
    dose_match: StratumMatch
    dose_studied: Optional[str] = None          # extracted from abstract
    form_match: StratumMatch
    form_studied: Optional[str] = None
    frequency_match: StratumMatch
    frequency_studied: Optional[str] = None
    population_match: StratumMatch
    population_studied: Optional[str] = None
    overall_applicability: Literal["direct", "partial", "generalisation"]
    applicability_reasoning: str


class StratumBucket(BaseModel):
    """Papers grouped by their relationship to the user's value for one slot."""
    slot: Literal["dose", "form", "frequency", "population"]
    user_value: Optional[str]                     # what the user said, or None
    strata: dict[StratumMatch, list[str]]         # stratum → list of paper_ids
    counts: dict[StratumMatch, int]
    stratum_verdicts: dict[StratumMatch, Literal[
        "supported", "contradicted", "insufficient_evidence", "empty"
    ]]
    stratum_reasoning: dict[StratumMatch, str]
```

### Extended VerdictResult

Add fields to the existing `VerdictResult` (don't break current shape):

```python
class VerdictResult(BaseModel):
    # ... existing fields stay unchanged ...

    # NEW: stratified view
    paper_stratifications: list[PaperStratification] = []
    stratum_buckets: list[StratumBucket] = []
    generalisation_warnings: list[str] = []
    # e.g. "Your question is about dietary turmeric but 38 of 40
    # retrieved papers study curcumin supplements at doses 50-500x
    # typical dietary intake. Evidence does not directly transfer."
```

### Contract with the frontend

The frontend gets back the same `AnalysisResponse` shape, now with
`paper_stratifications`, `stratum_buckets`, and
`generalisation_warnings` populated. The results page (Task 6) renders
the stratified view using these fields.

## File structure

```
src/synthesis/
  __init__.py
  schemas.py                    # EXTEND: add PaperStratification, StratumBucket
  paper_scorer.py               # EXTEND: stratification + stratified verdict
  stratifier.py                 # NEW: extracts paper values for stratifier slots
  stratum_assigner.py           # NEW: deterministic stratum matching logic

src/elicitation/
  priority_table.py             # EXTEND: annotate slots with role
  question_templates.py         # EXTEND: flag each template with role

frontend/src/
  components/
    StratifiedEvidence.tsx      # NEW: renders stratum buckets
    GeneralisationWarning.tsx   # NEW: renders warning panel
  api.ts                        # EXTEND: new response fields
  App.tsx                       # EXTEND: render new components

tests/
  test_stratifier.py            # NEW
  test_stratum_assigner.py      # NEW
  test_synthesis_stratified.py  # NEW: end-to-end stratified synthesis
  fixtures/
    stratification_test_cases.yaml   # NEW: 30+ hand-labeled cases
```

## Task 1 — Update `priority_table.py` to annotate roles

Change `DIMENSION_PRIORITY` from a flat list of slot names to a list
of `(slot_name, role)` tuples, OR keep the list and add a parallel
`DIMENSION_ROLE` dict. The latter is less invasive.

```python
# src/elicitation/priority_table.py

SlotRole = Literal["pre_retrieval", "stratifier"]

DIMENSION_ROLE: dict[str, SlotRole] = {
    "food":       "pre_retrieval",
    "outcome":    "pre_retrieval",
    "component":  "pre_retrieval",
    "dose":       "stratifier",
    "form":       "stratifier",
    "frequency":  "stratifier",
    "population": "stratifier",
}


def get_slot_role(slot: str) -> SlotRole:
    return DIMENSION_ROLE.get(slot, "stratifier")
```

Update the existing `get_priority(food)` to continue returning
ordered slot names — the elicitor still uses it unchanged. The role
dict is additive, consumed by the stratifier and by the results UI.

Tests:

- Every slot name that appears in any `DIMENSION_PRIORITY` list is
  present in `DIMENSION_ROLE`.
- `food`, `outcome`, `component` are `pre_retrieval`.
- `dose`, `form`, `frequency`, `population` are `stratifier`.

## Task 2 — Rewrite elicitation question framing for stratifier slots

Stratifier questions should be phrased so the user understands their
answer will organise results, not narrow the search. Update question
templates in `src/elicitation/question_templates.py`.

### Pre-retrieval question phrasing (unchanged)

> "Which health effect of coffee are you asking about?"

The user's answer determines which body of literature is searched.
The question is load-bearing. Wording stays as-is.

### Stratifier question phrasing (new pattern)

Old phrasing:

> "About how much coffee per day?"

New phrasing:

> "About how much coffee per day? (We'll search broadly and highlight
> studies that match your consumption level.)"

Old phrasing:

> "Are you asking about turmeric as food or as a supplement?"

New phrasing:

> "Are you asking about turmeric as food or as a supplement? (This
> doesn't narrow the search — we'll retrieve both and show you which
> studies apply to your form.)"

The rule: every stratifier question's text should include a
parenthetical that explains the answer will be used to *organise
results*, not to *narrow the search*. This manages user expectations
and makes it obvious why it's okay to answer "not sure" without
worrying that you're missing evidence.

Add a new field `role` to the `QuestionTemplate` TypedDict so the
elicitor can render the hint automatically:

```python
class QuestionTemplate(TypedDict):
    text: str
    options: list[str]
    option_values: list[str]
    allow_other: bool
    role: Literal["pre_retrieval", "stratifier"]
```

And add a shared helper that appends the stratifier hint to the text
when rendering:

```python
STRATIFIER_HINT = (
    " (We'll search broadly and group results by your answer, so "
    "answering 'not sure' won't narrow the evidence.)"
)

def render_question_text(template: QuestionTemplate) -> str:
    if template.get("role") == "stratifier":
        return template["text"] + STRATIFIER_HINT
    return template["text"]
```

Tests:

- Every stratifier template's rendered text ends with the stratifier
  hint.
- Every pre-retrieval template's rendered text is unchanged.
- The `role` field is present on every template.

## Task 3 — Paper value extractor (`stratifier.py`)

For each retrieved paper, extract the paper's studied values for each
stratifier slot, from the abstract. This is an LLM call per paper
with structured output.

```python
# src/synthesis/stratifier.py

from pydantic import BaseModel
from typing import Optional

from src.extraction.llm_client import LLMClient


class ExtractedPaperValues(BaseModel):
    """What the paper itself studied — extracted from abstract."""
    paper_id: str
    dose_studied: Optional[str]              # e.g. "500 mg/day", "2-3 cups/day"
    form_studied: Optional[str]              # e.g. "dietary", "supplement", "extract"
    frequency_studied: Optional[str]         # e.g. "daily", "weekly"
    population_studied: Optional[str]        # e.g. "healthy adults", "T2D patients"
    extraction_reasoning: str                # brief justification


STRATIFIER_EXTRACTION_PROMPT = """\
You extract four specific features from a research paper abstract:
what dose/amount, form, frequency, and population were studied. Return
values that the paper ACTUALLY reports. If the paper doesn't report a
feature, return null. Do NOT infer values from context or common
practice.

Return a JSON object matching the schema. Be brief and factual.

EXAMPLES

Abstract: "We conducted a randomized trial of curcumin supplementation
at 500 mg twice daily for 12 weeks in 80 adults with knee
osteoarthritis..."
Output: {
  "dose_studied": "1000 mg/day (500 mg twice daily)",
  "form_studied": "supplement",
  "frequency_studied": "daily",
  "population_studied": "adults with knee osteoarthritis",
  "extraction_reasoning": "Explicit dose and form stated; population specified."
}

Abstract: "This meta-analysis of 11 observational cohort studies examined
dietary turmeric intake from spice consumption and inflammatory markers..."
Output: {
  "dose_studied": null,
  "form_studied": "dietary",
  "frequency_studied": null,
  "population_studied": "general adult populations (meta-analysis)",
  "extraction_reasoning": "Form is dietary; dose and frequency not reported in abstract."
}

Abstract: "In vitro study of curcumin at 10 µM on HeLa cell proliferation..."
Output: {
  "dose_studied": "10 µM (in vitro concentration)",
  "form_studied": "isolated compound",
  "frequency_studied": null,
  "population_studied": "HeLa cell line (in vitro)",
  "extraction_reasoning": "In vitro; population is cell line, not human."
}
"""


def extract_paper_values(
    paper: "ScorePaper", llm: LLMClient
) -> ExtractedPaperValues:
    ...
```

Performance note: one LLM call per paper × 40 papers = 40 calls. Use
`thinking_budget=0` (structured factual extraction, no reasoning
needed) and run in a thread pool with `max_workers=4` (respecting
Gemini rate limits). Target: under 30 seconds for 40 papers.

Tests:

- Scripted LLM provider; verify each example above produces the
  expected output.
- Verify `null` handling: paper that doesn't report dose returns
  `dose_studied=None`, not an empty string or "N/A" or "unknown".
- Rate limit: verify thread pool doesn't exceed 4 concurrent calls.

## Task 4 — Stratum assigner (`stratum_assigner.py`)

Deterministic logic that compares paper values (from Task 3) to user
values (from elicitation) and assigns each paper a stratum match per
slot.

```python
# src/synthesis/stratum_assigner.py

from typing import Literal, Optional
from src.synthesis.schemas import StratumMatch


def assign_dose_stratum(
    user_value: Optional[str],
    paper_value: Optional[str],
) -> StratumMatch:
    """Compare user's stated dose to paper's studied dose.

    Uses token-level dose comparison. Requires both values to be
    parseable numerics; otherwise returns 'unreported' or 'not_applicable'.
    """
    if user_value is None:
        return "not_applicable"
    if paper_value is None:
        return "unreported"
    user_num = _parse_dose_to_numeric(user_value)
    paper_num = _parse_dose_to_numeric(paper_value)
    if user_num is None or paper_num is None:
        return "unreported"
    ratio = paper_num / user_num
    if 0.5 <= ratio <= 2.0:
        return "matches"
    if ratio > 2.0:
        return "higher"
    return "lower"


def assign_form_stratum(
    user_value: Optional[str],
    paper_value: Optional[str],
) -> StratumMatch:
    if user_value is None:
        return "not_applicable"
    if paper_value is None:
        return "unreported"
    # Normalise both to canonical form tokens.
    u = _canonical_form(user_value)
    p = _canonical_form(paper_value)
    if u == p:
        return "matches"
    return "different"


# ... similar for frequency and population ...


def _parse_dose_to_numeric(raw: str) -> Optional[float]:
    """Pull a numeric value from dose text. '500 mg twice daily' → 1000.
    '2-3 cups/day' → 2.5. Returns None on failure."""
    ...


def _canonical_form(raw: str) -> str:
    """Normalise form strings: 'supplement' / 'supplements' / 'pill' →
    'supplement'. 'dietary' / 'whole food' / 'from food' → 'dietary'."""
    ...
```

Key design notes:

- **Dose ratios, not absolute values.** 500mg vs. 1000mg is "higher"
  regardless of what the substance is. Ratio of 2.0 is the threshold
  for "different tier." Ratio of 0.5 is the opposite threshold.
- **Form uses a canonical token table.** Hand-curate mappings from
  common English phrasings to `{dietary, supplement, extract,
  isolated_compound, topical, other}`. Bad form normalisation
  completely undermines stratification; spend real time here.
- **Population is the trickiest.** "Healthy adults" and "adults aged
  20-45" should match. "Children" and "adults" shouldn't. "Pregnant
  women" and "adults" shouldn't. Use a small LLM call for population
  matching if deterministic rules get too hairy — but prefer rules.

Tests:

- 20+ dose assignment cases across thresholds.
- Form canonicalisation for 30+ common phrasings.
- Population overlap cases including pregnant/not-pregnant,
  adult/child, healthy/diseased.

## Task 5 — Stratified synthesis (`paper_scorer.py`)

Modify `analyze_claim` to produce the stratified output alongside the
existing verdict.

```python
# src/synthesis/paper_scorer.py

def analyze_claim(
    request: ScoreRequest,
    locked_pico: LockedPICO,
    model: str = DEFAULT_MODEL,
    log_file: str | None = None,
) -> AnalysisResponse:
    # 1. Existing: score papers for relevance + stance.
    scored = score_papers(request, model=model)

    # 2. NEW: extract paper values for each stratifier slot.
    extracted_values = extract_values_in_parallel(
        request.papers, model=model
    )

    # 3. NEW: assign strata per paper.
    stratifications = [
        PaperStratification(
            paper_id=p.paper_id,
            dose_match=assign_dose_stratum(
                locked_pico.dose, extracted_values[p.paper_id].dose_studied
            ),
            dose_studied=extracted_values[p.paper_id].dose_studied,
            # ... similarly for form, frequency, population
            overall_applicability=_classify_overall(extracted_values[p.paper_id], locked_pico),
            applicability_reasoning=_build_reasoning(
                extracted_values[p.paper_id], locked_pico
            ),
        )
        for p in request.papers
    ]

    # 4. NEW: build stratum buckets.
    buckets = build_stratum_buckets(
        scored.results, stratifications, locked_pico
    )

    # 5. NEW: compute stratum-level verdicts.
    for bucket in buckets:
        bucket.stratum_verdicts = compute_stratum_verdicts(
            bucket, scored.results
        )
        bucket.stratum_reasoning = compose_stratum_reasoning(
            bucket, scored.results
        )

    # 6. NEW: generalisation warnings.
    warnings = detect_generalisation_warnings(
        stratifications, locked_pico
    )

    # 7. Existing: overall verdict, now aware of stratum weighting.
    verdict = generate_verdict(
        user_claim=request.user_claim,
        user_profile=request.user_profile,
        scored=scored.results,
        papers_by_id={p.paper_id: p for p in request.papers},
        stratifications=stratifications,  # NEW arg
        generalisation_warnings=warnings,  # NEW arg
        model=model,
    )

    verdict.paper_stratifications = stratifications
    verdict.stratum_buckets = buckets
    verdict.generalisation_warnings = warnings

    # 8. Logging and return as before.
    ...
```

### Overall verdict must respect stratification

The existing verdict prompt doesn't know about strata. Extend the
system prompt to say:

> When the user stated a specific dose / form / frequency / population,
> weight papers in the matching stratum more heavily than papers in
> other strata. If papers in the matching stratum disagree with
> papers in other strata, the matching stratum wins for the user's
> specific claim. Mention this explicitly in `verdict_reasoning` when
> it happens.

This is the one prompt change in the verdict step. The rest of the
verdict logic is unchanged — it just has richer inputs.

### Generalisation warning logic

```python
def detect_generalisation_warnings(
    stratifications: list[PaperStratification],
    locked_pico: LockedPICO,
) -> list[str]:
    warnings = []
    total = len(stratifications)
    if total == 0:
        return warnings

    # Form mismatch: most papers study a different form than user asked.
    form_different = sum(
        1 for s in stratifications if s.form_match == "different"
    )
    if locked_pico.form and form_different / total >= 0.5:
        warnings.append(
            f"You asked about {locked_pico.form} {locked_pico.food}, "
            f"but {form_different} of {total} retrieved papers study "
            f"a different form. Evidence may not transfer directly."
        )

    # Dose mismatch: most papers at substantially different dose.
    dose_different = sum(
        1 for s in stratifications if s.dose_match in ("higher", "lower")
    )
    if locked_pico.dose and dose_different / total >= 0.5:
        direction = "higher" if (
            sum(1 for s in stratifications if s.dose_match == "higher")
            > sum(1 for s in stratifications if s.dose_match == "lower")
        ) else "lower"
        warnings.append(
            f"You asked about {locked_pico.dose}, but most retrieved "
            f"evidence studies substantially {direction} doses."
        )

    # Population mismatch, similarly.
    ...

    return warnings
```

Tests:

- Synthesize on a fixture where all papers match the user's values →
  no warnings, verdict unchanged shape.
- Synthesize on a fixture where 38 of 40 papers are supplement form
  and user asked dietary → exactly one form warning generated, with
  the right counts.
- Synthesize on a fixture where strata disagree (supplement papers
  say yes, dietary papers say no) → verdict_reasoning explicitly
  mentions the stratum split.

## Task 6 — Frontend: stratified evidence UI

The existing results page shows one flat list of cited papers grouped
by stance (supporting / contradicting / neutral). Add a new section
above it that shows the stratified view.

### Layout

```
┌────────────────────────────────────────────────────────────┐
│ VERDICT: [existing block]                                  │
├────────────────────────────────────────────────────────────┤
│ ⚠ GENERALISATION WARNINGS                                   │
│ • You asked about dietary turmeric, but 38 of 40 retrieved │
│   papers study curcumin supplements at 50-500x typical     │
│   dietary intake. Evidence does not directly transfer.     │
├────────────────────────────────────────────────────────────┤
│ EVIDENCE BY YOUR SPECIFIC QUESTION                          │
│                                                             │
│ Your dose: 3-4 cups/day                                    │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│   ● Studies at your level (3-4 cups/day)    14 papers     │
│     Finding: supported, 10/14 consistent                   │
│   ● Studies at higher doses (5+ cups/day)    6 papers     │
│     Finding: mixed, 3/6 consistent                         │
│   ● Studies at lower doses (1-2 cups/day)   11 papers     │
│     Finding: supported, 9/11 consistent                    │
│   ● Unreported dose                           9 papers     │
│                                                             │
│ Your form: dietary (whole food)                            │
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│   ● Studies matching your form (dietary)      3 papers    │
│     ⚠ Evidence in your form is sparse                     │
│   ● Studies on other forms (supplement)     35 papers     │
│                                                             │
├────────────────────────────────────────────────────────────┤
│ [Existing stance tabs — Supporting / Contradicting / Neutral] │
└────────────────────────────────────────────────────────────┘
```

### Components

**`StratifiedEvidence.tsx`**: renders one `StratumBucket` per
stratifier slot with a user-stated value. Clicking a stratum expands
to show the specific papers in that stratum with their extracted
values inline (e.g., "PMID 12345 — studied 800 mg/day; user asked
about 3-4 cups/day (~300 mg caffeine)").

**`GeneralisationWarning.tsx`**: renders the warnings panel. Yellow
accent, clear wording, positioned between verdict block and stratified
evidence.

**`App.tsx`**: wire both into the results stage. New components go
above the existing stance tabs. Existing stance tabs remain — users
who want "just the supporting papers" still get that view.

### Empty-state handling

If the user didn't provide a value for a stratifier slot (they chose
"not sure" in elicitation), don't render a stratum block for that slot
at all. Only render blocks for slots the user answered.

If a stratum block would have all papers in `unreported` (papers don't
state the value), render a small note instead: "Papers don't report
this information consistently; we can't stratify on {slot}."

Tests: render the component with fixtures covering (a) user value
given + clean strata, (b) user said "not sure" → no block, (c) all
papers unreported → note shown, (d) all papers in one stratum →
block still renders, shows concentration.

## Task 7 — Evaluation set

Create `tests/fixtures/stratification_test_cases.yaml`. 30+ cases
covering:

- User states all four stratifier slots; papers are mixed.
- User states dose only; form/freq/pop are N/A for stratification.
- User's form matches minority of papers (generalisation warning).
- User's dose is higher than all papers.
- User's population is narrower than any paper (e.g., "pregnant Type 1
  diabetics" and no paper studies that intersection).

Each case:

```yaml
- name: <descriptive name>
  locked_pico:
    food: <str>
    outcome: <str>
    dose: <str | null>
    form: <str | null>
    frequency: <str | null>
    population: <str | null>
  papers:
    - paper_id: <str>
      extracted_values:
        dose_studied: <str | null>
        form_studied: <str | null>
        frequency_studied: <str | null>
        population_studied: <str | null>
      stance: <supports | contradicts | neutral | unclear | not_applicable>
  expected:
    stratum_counts:
      dose: { matches: <n>, higher: <n>, lower: <n>, unreported: <n> }
      form: { matches: <n>, different: <n>, unreported: <n> }
      # etc
    generalisation_warnings:
      - <expected warning substring>
    stratum_verdict:
      dose:
        matches: <supported | contradicted | insufficient_evidence | empty>
        # etc
```

Run this fixture in `test_synthesis_stratified.py`. Assert stratum
counts are exact; assert warnings contain expected substrings
(substring, not exact match, since phrasing will vary).

## Task 8 — Log the stratification

Add to `logs/synthesis.jsonl` record:

```json
{
  ...,
  "stratifications": [
    {"paper_id": "...", "dose_match": "matches", "dose_studied": "...", ...},
    ...
  ],
  "stratum_buckets": [
    {"slot": "dose", "user_value": "3-4 cups/day", "counts": {...}, ...}
  ],
  "generalisation_warnings": [...]
}
```

This is audit-critical. When a user or reviewer asks "why did the
verdict change when I answered this question differently," the log
shows how each paper's stratum assignment changed and how that
rippled into stratum verdicts.

## Non-goals

- **Do not convert stratifier slots into query-narrowing filters.**
  That's the old behaviour, and the whole point of this patch is
  that narrowing is harmful for these slots.
- **Do not try to extract dose/form/etc. from full papers.** Abstract
  only. If the abstract doesn't report it, the paper's value is
  `unreported` and the paper lands in the `unreported` stratum.
- **Do not stratify on `outcome` or `component`.** Those are
  pre-retrieval slots; they already shape the query and don't need
  post-retrieval stratification.
- **Do not auto-re-retrieve when strata are empty.** If the user's
  stratum has 0 papers, that's information worth surfacing ("evidence
  in your specific stratum is sparse"), not a reason to silently
  broaden the query behind their back.

## Dependencies

- No new external dependencies.
- Existing `LLMClient`, `google-genai`, `pydantic`, `pyyaml`.

## Environment variables

Unchanged. `GEMINI_API_KEY` / `GOOGLE_API_KEY`.

## Deliverable

When done, I should be able to run:

```python
from src.extraction import ClaimExtractor, LLMClient
from src.elicitation import ElicitationAgent, CLIAdapter
from src.retrieval import RetrievalAgent
from src.synthesis import analyze_claim, ScoreRequest, UserProfile

# ... normal pipeline setup ...

result = analyze_claim(request, locked_pico)

# New outputs available:
assert result.verdict.paper_stratifications, "per-paper strata present"
assert result.verdict.stratum_buckets, "bucket views present"

# For the turmeric/inflammation case with locked_pico.form='dietary':
dietary_bucket = next(
    b for b in result.verdict.stratum_buckets if b.slot == "form"
)
assert dietary_bucket.counts["different"] > dietary_bucket.counts["matches"]
assert any(
    "dietary" in w and "supplement" in w
    for w in result.verdict.generalisation_warnings
), "form-mismatch warning generated"

# Elicitation questions now have visible downstream consumers:
#  - 'form' answer produced the dietary-vs-supplement stratum
#  - 'dose' answer produced the dose strata
#  - etc.
```

And for the coffee/CVD case the results UI shows:

> Your dose: 3-4 cups/day
>   Studies at your level: 14 papers, supported
>   Studies at higher doses: 6 papers, mixed
>   Studies at lower doses: 11 papers, supported

with the stratum counts exactly matching the counts in the log.

## Start with Task 1

Please implement Task 1 (annotate slot roles in `priority_table.py`)
first, including tests, and stop so I can review before moving on.
Tasks 2–8 build on top and should be done in order.
