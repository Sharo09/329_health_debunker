"""F2/F3/F4 — LLM-based judgment on feasibility, mechanism, and frame.

One structured LLM call produces a ``MechanismJudgment`` over three
independent axes. The checker translates the judgment into zero or more
``PlausibilityFailure`` entries. Dose is **not** evaluated here — the
prompt is explicit about ignoring dose magnitude so the deterministic
F1 check stays the single source of truth for dose.
"""

from __future__ import annotations

from pydantic import BaseModel

from src.plausibility.schemas import PlausibilityFailure


MECHANISM_SYSTEM_PROMPT = """\
You evaluate whether a health claim is worth investigating empirically.
You do NOT evaluate whether the claim is true - that requires literature
review. You evaluate three specific properties.

IMPORTANT: Dose plausibility is handled by a separate deterministic
checker. Do NOT comment on dose. Even if the claim mentions an extreme
dose, evaluate only whether the non-dose aspects of the claim are
feasible, coherent, and in a scientific frame.

1. FEASIBILITY - can a human actually do what the claim describes, for
   long enough and with enough people to have been studied?
     Feasible:   "eat an apple a day for a month"
     Feasible:   "take 1000mg vitamin C daily for 10 years"
     Borderline: "eat only meat for 6 months" (few people sustain this;
                 evidence will be sparse / case reports)
     Infeasible: "never drink water for a week" (death within ~3 days)

2. MECHANISM COHERENCE - is the proposed causal pathway consistent
   with basic physiology, chemistry, or biology?
     Coherent:   "vitamin C supports immune function"
     Incoherent: "alkaline water neutralises acid in cancer cells to
                 reverse cancer" (stomach acidifies all ingested water
                 immediately; blood pH is tightly homeostatic; cancer
                 biology is not primarily pH-driven)
     Incoherent: "eating raw onions pulls toxins out through the soles
                 of the feet"

3. SCIENTIFIC FRAME - is the claim in a frame where empirical testing
   is meaningful?
     In frame:     any claim with a definable intervention and outcome
     Out of frame: "crystal vibrations in food enhance chakra alignment"
                   (terms are undefined; no testable prediction)

For each property, return a boolean (true = the property holds, the
claim is worth investigating on this axis) and a 1-2 sentence reason.

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


class MechanismJudgment(BaseModel):
    is_feasible: bool
    feasibility_reasoning: str
    mechanism_is_coherent: bool
    mechanism_reasoning: str
    is_in_scientific_frame: bool
    frame_reasoning: str


def check_mechanism(
    claim_text: str,
    llm_client,
) -> list[PlausibilityFailure]:
    """Evaluate F2/F3/F4 in one LLM call; return matching failures.

    Returns an empty list when the claim passes all three axes. F2 is
    always a warning (thin evidence is still evidence); F3 and F4 are
    blocking (incoherent mechanism or out-of-frame claim can't be
    rescued by retrieval).
    """
    messages = [
        {"role": "system", "content": MECHANISM_SYSTEM_PROMPT},
        {"role": "user", "content": f"Claim: {claim_text}\nOutput:"},
    ]
    judgment = llm_client.extract(messages, MechanismJudgment)

    failures: list[PlausibilityFailure] = []
    raw = judgment.model_dump()

    if not judgment.is_feasible:
        failures.append(PlausibilityFailure(
            failure_type="F2_feasibility",
            severity="warning",
            reasoning=judgment.feasibility_reasoning,
            supporting_data={"raw_judgment": raw},
        ))
    if not judgment.mechanism_is_coherent:
        failures.append(PlausibilityFailure(
            failure_type="F3_mechanism",
            severity="blocking",
            reasoning=judgment.mechanism_reasoning,
            supporting_data={"raw_judgment": raw},
        ))
    if not judgment.is_in_scientific_frame:
        failures.append(PlausibilityFailure(
            failure_type="F4_frame",
            severity="blocking",
            reasoning=judgment.frame_reasoning,
            supporting_data={"raw_judgment": raw},
        ))
    return failures
