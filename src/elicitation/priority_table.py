"""Per-food priority ordering of which PICO slots to clarify first.

Priorities are hard-coded. The first slot in each list is the most
important ambiguity to resolve for that food; the elicitor walks the
list in order and asks up to `MAX_QUESTIONS` questions.

Slot roles (Elicitation Patch B) partition slots into two downstream
consumers:

- ``pre_retrieval`` — the slot value materially narrows the PubMed
  query (``food``, ``outcome``, ``component``).
- ``stratifier`` — the slot value is used post-retrieval to partition,
  weight, and annotate retrieved papers rather than to narrow the
  query (``dose``, ``form``, ``frequency``, ``population``).

Both roles are still elicited from the user; the difference is only in
how downstream stages consume the answer. Priority ordering (i.e.
which slot gets asked first) is independent of the role — a stratifier
slot can still be top priority for a given food.
"""

from difflib import get_close_matches
from typing import Literal

DIMENSION_PRIORITY: dict[str, list[str]] = {
    # Outcome varies wildly (heart disease vs. pregnancy vs. sleep); dose
    # (cups/day) is the next biggest moderator in the literature.
    "coffee": ["outcome", "population", "dose"],
    # Culinary turmeric and standardized curcumin extracts are studied
    # separately; form is the dominant axis.
    "turmeric": ["form", "outcome", "population"],
    # Processed vs. unprocessed red meat is the form split that matters
    # most; outcome (CVD vs. cancer) and dose follow.
    "red meat": ["outcome", "form", "dose"],
    # Cholesterol/CVD studies cluster by population (diabetic vs. healthy)
    # and by how many eggs/week.
    "eggs": ["outcome", "population", "frequency"],
    # Effects are almost entirely dose-dependent (moderate vs. heavy);
    # population (e.g., pregnancy) flips the sign of some outcomes.
    "alcohol": ["dose", "outcome", "population"],
    # D2 vs. D3 vs. sun exposure; IU/day; and deficient vs. replete
    # populations all matter.
    "vitamin d": ["form", "dose", "population"],
    # Many protocols (16:8, 5:2, ADF); population is the biggest moderator.
    "intermittent fasting": ["population", "outcome", "frequency"],
    # Aspartame, sucralose, stevia differ; outcome (cancer vs. glucose vs.
    # microbiome) drives the literature split.
    "artificial sweeteners": ["outcome", "population", "dose"],
    # Outcome (obesity vs. dental vs. CVD) and dose are the axes.
    "added sugar": ["outcome", "dose", "population"],
    # Lactose intolerance and pediatric vs. adult studies dominate.
    "dairy milk": ["population", "outcome", "form"],
}

DEFAULT_PRIORITY: list[str] = ["outcome", "population", "form"]

SlotRole = Literal["pre_retrieval", "stratifier"]

# Role classification for every slot that can appear in a priority list
# or in the flat PartialPICO. ``food`` is included for completeness —
# it is always in the query and is never elicited, but downstream
# consumers may still ask for its role.
DIMENSION_ROLE: dict[str, SlotRole] = {
    "food":       "pre_retrieval",
    "outcome":    "pre_retrieval",
    "component":  "pre_retrieval",
    "dose":       "stratifier",
    "form":       "stratifier",
    "frequency":  "stratifier",
    "population": "stratifier",
}

_FUZZY_CUTOFF = 0.8


def get_priority(food: str | None) -> list[str]:
    """Return the ordered priority slots for a food.

    Case-insensitive with whitespace trimming; falls back to a fuzzy
    match (e.g., "coffees" → "coffee") before returning DEFAULT_PRIORITY.
    """
    if not food:
        return list(DEFAULT_PRIORITY)

    key = food.strip().lower()
    if key in DIMENSION_PRIORITY:
        return list(DIMENSION_PRIORITY[key])

    matches = get_close_matches(
        key, DIMENSION_PRIORITY.keys(), n=1, cutoff=_FUZZY_CUTOFF
    )
    if matches:
        return list(DIMENSION_PRIORITY[matches[0]])

    return list(DEFAULT_PRIORITY)


def get_slot_role(slot: str) -> SlotRole:
    """Return the downstream role for a slot.

    Unknown slots default to ``"stratifier"`` — the safe choice, since
    a stratifier slot never narrows the query (so mislabelling a slot
    as stratifier cannot cause the pipeline to miss evidence).
    """
    return DIMENSION_ROLE.get(slot, "stratifier")
