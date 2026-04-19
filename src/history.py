"""History and popular claims logic.

Pure data layer — no routing here. Endpoints live in backend/main.py
alongside all other /api/* routes.

    GET /api/history?limit=50   — served by backend/main.py
    GET /api/popular-claims     — served by backend/main.py
"""

from __future__ import annotations

import json
import os

from pydantic import BaseModel

from src.synthesis.schemas import UserProfile, Verdict

SYNTHESIS_LOG_FILE = "logs/synthesis.jsonl"

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class HistoryEntry(BaseModel):
    """Summary of one past analysis, derived from the synthesis JSONL log."""
    timestamp: str
    user_claim: str
    user_profile: UserProfile
    verdict: Verdict
    confidence_percent: float
    verdict_reasoning: str
    demographic_caveat: str | None
    papers_scored: int
    stance_counts: dict[str, int]


class PopularClaim(BaseModel):
    """A pre-curated claim shown on the Popular tab."""
    claim: str


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def get_history(
    log_file: str = SYNTHESIS_LOG_FILE,
    limit: int = 50,
) -> list[HistoryEntry]:
    """Return past analyses from the synthesis JSONL log, most recent first."""
    if not os.path.exists(log_file):
        return []
    entries: list[HistoryEntry] = []
    with open(log_file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                entries.append(HistoryEntry(
                    timestamp=record["timestamp"],
                    user_claim=record["user_claim"],
                    user_profile=UserProfile(**record["user_profile"]),
                    verdict=record["verdict"],
                    confidence_percent=record["confidence_percent"],
                    verdict_reasoning=record["verdict_reasoning"],
                    demographic_caveat=record.get("demographic_caveat"),
                    papers_scored=record["papers_scored"],
                    stance_counts=record.get("stance_counts", {}),
                ))
            except (KeyError, ValueError):
                continue
    return list(reversed(entries))[:limit]


# ---------------------------------------------------------------------------
# Popular claims
# ---------------------------------------------------------------------------

_POPULAR_CLAIMS: list[str] = [
    # Seed oils & fats
    "Seed oils cause inflammation because of omega-6.",
    # Processed & charred food
    "Processed meats cause cancer because of nitrites.",
    "Charred food causes cancer.",
    # Anti-nutrients
    "Oxalates cause kidney stones for everyone.",
    "Lectins are toxic.",
    "Phytates block all mineral absorption.",
    # Artificial sweeteners
    "Artificial sweeteners spike insulin.",
    "Artificial sweeteners destroy gut bacteria.",
    "Artificial sweeteners cause cancer.",
    # Fish
    "Fish is dangerous because of mercury.",
    # Gluten & wheat
    "Gluten is inflammatory for everyone.",
    "Modern wheat is uniquely harmful.",
    # Coffee
    "Coffee is dehydrating.",
    "Coffee is bad for your heart.",
    "Coffee is protective against disease.",
    # Alcohol
    "Red wine is healthy because of resveratrol.",
    "Alcohol in small amounts is good for you.",
]


def get_popular_claims() -> list[PopularClaim]:
    """Return the curated list of popular claims for the Popular tab."""
    return [PopularClaim(claim=c) for c in _POPULAR_CLAIMS]
