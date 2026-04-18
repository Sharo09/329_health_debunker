"""End-to-end demo: Stations 1 → 2 → 3.

Usage:
    export GOOGLE_API_KEY=your_gemini_key        # required for Station 1
    export NCBI_API_KEY=your_ncbi_key            # optional; raises PubMed rate limit
    python3 demo.py                               # default claim
    python3 demo.py "Is a lot of coffee bad during pregnancy?"
"""

import sys

from src.elicitation import CLIAdapter, ElicitationAgent
from src.extraction import ClaimExtractor, LLMClient
from src.retrieval import RetrievalAgent


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
    result = RetrievalAgent().retrieve(locked)

    print(f"Query used       : {result.query_used}")
    print(f"Relaxation level : {result.relaxation_level}")
    print(f"Total PubMed hits: {result.total_pubmed_hits}")
    print(f"Papers returned  : {len(result.papers)}")
    print(f"Below threshold  : {result.below_threshold}")

    if result.papers:
        top_n = min(5, len(result.papers))
        print()
        print(f"--- Top {top_n} papers ---")
        for i, p in enumerate(result.papers[:top_n], start=1):
            year = p.pub_year or "n.d."
            print(f"[{i}] PMID {p.pmid} ({year})  {p.journal}")
            print(f"    {p.title}")
            if p.is_retracted:
                print("    *** RETRACTED ***")
    return 0


if __name__ == "__main__":
    sys.exit(main())
