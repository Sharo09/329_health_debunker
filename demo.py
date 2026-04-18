"""End-to-end demo: Stations 1 → 2 → 3 → 4.

Usage:
    export GOOGLE_API_KEY=your_gemini_key        # Stations 1 & 4
    export NCBI_API_KEY=your_ncbi_key            # Station 3 (optional)
    python3 demo.py                               # default claim
    python3 demo.py "Is a lot of coffee bad during pregnancy?"
"""

import sys

from src.elicitation import CLIAdapter, ElicitationAgent
from src.extraction import ClaimExtractor, LLMClient
from src.retrieval import RetrievalAgent
from src.retrieval.schemas import Paper as RetrievedPaper
from src.synthesis import (
    Paper as ScorePaper,
    ScoreRequest,
    UserProfile,
    analyze_claim,
)

# Cap on papers passed to Station 4. The scorer sends every paper in a
# single Gemini call; 40 abstracts still fit well within Flash's 1M
# context and cost ~$0.004 per run. Raise to include more evidence, or
# set to None to pass everything retrieval returned.
SYNTHESIS_PAPER_CAP = 40

# Map Station 2's population tokens → Station 4's DemographicGroup literal.
_POPULATION_TO_DEMOGRAPHIC: dict[str, str] = {
    "healthy_adults": "adults",
    "healthy_replete": "adults",
    "children": "children",
    "infants": "infants",
    "adolescents": "adolescents",
    "elderly": "older_adults",
    "pregnant": "adults",
    "obese": "adults",
    "diabetic": "adults",
    "hypercholesterolemia": "adults",
    "deficient": "adults",
    "inflammatory_patients": "adults",
    "cardiovascular_patients": "adults",
    "liver_patients": "adults",
    "lactose_intolerant": "general",
    "condition": "general",
}


def _retrieved_to_score_paper(p: RetrievedPaper) -> ScorePaper:
    """Adapt Station 3's Paper to Station 4's Paper schema.

    Station 4 wants `extracted_claim` — a 1–3 sentence conclusion.  We
    don't have one, so we use the last two sentences of the abstract as
    a proxy. Not perfect, but reasonable for a demo.
    """
    abstract = p.abstract or p.title
    sentences = [s.strip() for s in abstract.split(".") if s.strip()]
    if len(sentences) >= 2:
        claim = sentences[-2] + ". " + sentences[-1] + "."
    elif sentences:
        claim = sentences[-1] + "."
    else:
        claim = abstract[:300]

    return ScorePaper(
        paper_id=p.pmid,
        title=p.title,
        extracted_claim=claim,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{p.pmid}/",
        population_studied=None,
        nutritional_components=[],
    )


def _locked_to_user_profile(locked) -> UserProfile:
    demographic = _POPULATION_TO_DEMOGRAPHIC.get(
        (locked.population or "").lower(), "general"
    )
    return UserProfile(demographic_group=demographic)


def main() -> int:
    claim = sys.argv[1] if len(sys.argv) > 1 else "Is turmeric good for inflammation?"

    print()
    print(f"CLAIM: {claim}")

    # ---- Station 1: Extraction ------------------------------------------
    print()
    print("=" * 72)
    print("STATION 1 — Extraction (Gemini)")
    print("=" * 72)
    rich = ClaimExtractor(LLMClient(model="gemini-2.5-flash")).extract(claim)
    print(rich.model_dump_json(indent=2))

    if not rich.is_food_claim:
        print()
        print(f"Rejected (not a food/nutrition claim): {rich.scope_rejection_reason}")
        return 0

    # ---- Station 2: Elicitation -----------------------------------------
    print()
    print("=" * 72)
    print("STATION 2 — Elicitation (answer at the prompts)")
    print("=" * 72)
    locked = ElicitationAgent(CLIAdapter()).elicit(rich.to_flat())

    print()
    print("--- Locked PICO ---")
    print(locked.model_dump_json(indent=2))

    # ---- Station 3: Retrieval -------------------------------------------
    print()
    print("=" * 72)
    print("STATION 3 — Retrieval (PubMed)")
    print("=" * 72)
    retrieval = RetrievalAgent().retrieve(locked)

    print(f"Query used       : {retrieval.query_used}")
    print(f"Relaxation level : {retrieval.relaxation_level}")
    print(f"Total PubMed hits: {retrieval.total_pubmed_hits}")
    print(f"Papers returned  : {len(retrieval.papers)}")
    print(f"Below threshold  : {retrieval.below_threshold}")

    if not retrieval.papers:
        print()
        print("No papers retrieved — cannot synthesize a verdict.")
        return 0

    # ---- Station 4: Synthesis -------------------------------------------
    print()
    print("=" * 72)
    print("STATION 4 — Synthesis (Gemini)")
    print("=" * 72)

    papers_for_scoring = [
        _retrieved_to_score_paper(p)
        for p in retrieval.papers[:SYNTHESIS_PAPER_CAP]
    ]
    request = ScoreRequest(
        user_claim=claim,
        user_profile=_locked_to_user_profile(locked),
        papers=papers_for_scoring,
    )
    print(f"Scoring {len(papers_for_scoring)} papers...")
    analysis = analyze_claim(request)

    v = analysis.verdict
    print()
    print(f"VERDICT         : {v.verdict.upper()}")
    print(f"Confidence      : {v.confidence_percent:.0f}%")
    if v.demographic_caveat:
        print(f"Caveat          : {v.demographic_caveat}")
    print()
    print(f"Reasoning:")
    print(f"  {v.verdict_reasoning}")

    for heading, bucket in (
        ("Supporting papers", v.supporting_papers),
        ("Contradicting papers", v.contradicting_papers),
        ("Neutral / inconclusive", v.neutral_papers),
    ):
        if bucket:
            print()
            print(f"--- {heading} ({len(bucket)}) ---")
            for cp in bucket:
                print(f"  [{cp.stance}] PMID {cp.paper_id}  rel={cp.relevance_score:.2f}")
                print(f"    {cp.title}")
                print(f"    {cp.one_line_summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
