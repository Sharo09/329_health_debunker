"""End-to-end demo: Station 1 (extraction) + Station 2 (elicitation).

Usage:
    export GOOGLE_API_KEY=your_key_here
    python3 demo.py                                    # default claim
    python3 demo.py "Is a lot of coffee bad during pregnancy?"
"""

import sys

from src.elicitation import CLIAdapter, ElicitationAgent
from src.extraction import ClaimExtractor, LLMClient


def main() -> int:
    claim = sys.argv[1] if len(sys.argv) > 1 else "Is turmeric good for inflammation?"

    print()
    print(f"CLAIM: {claim}")
    print()
    print("--- Station 1: Extraction ---")
    rich = ClaimExtractor(LLMClient(model="gemini-2.5-flash")).extract(claim)
    print(rich.model_dump_json(indent=2))

    if not rich.is_food_claim:
        print()
        print(f"Rejected (not a food/nutrition claim): {rich.scope_rejection_reason}")
        return 0

    print()
    print("--- Station 2: Elicitation (answer at the prompts) ---")
    locked = ElicitationAgent(CLIAdapter()).elicit(rich.to_flat())

    print()
    print("--- Locked PICO (ready for Station 3) ---")
    print(locked.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
