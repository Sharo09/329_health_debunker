"""Food name normalization.

Maps raw user strings ("cofee", "a cup of joe", "tumeric") to canonical
food names from the curated demo set. Unknown foods are passed through
verbatim (lowercased, stripped) with `is_in_known_list=False`.

Matching strategy, in order:
  1. Exact match of the lowercased input against any alias.
  2. Substring match: any alias is contained in the input (catches
     "a cup of joe" → "coffee" via "cup of joe").
  3. Fuzzy match via rapidfuzz edit-ratio with a threshold of 85.
     (We use plain ``fuzz.ratio`` rather than ``WRatio`` because
     ``WRatio``'s partial-match component scores unrelated strings like
     "leggings" vs "egg" at 90, causing false positives.)
"""

from rapidfuzz import fuzz, process

KNOWN_FOODS: dict[str, list[str]] = {
    "coffee": ["coffee", "coffees", "cup of joe", "espresso", "java"],
    "turmeric": ["turmeric", "curcuma", "haldi", "curcumin"],
    "red meat": ["red meat", "beef", "pork", "lamb", "steak"],
    "processed meat": [
        "processed meat",
        "bacon",
        "hot dog",
        "hot dogs",
        "deli meat",
        "sausage",
    ],
    "eggs": ["egg", "eggs"],
    "alcohol": ["alcohol", "wine", "beer", "liquor", "spirits"],
    "vitamin D": ["vitamin d", "vit d", "vitamin-d"],
    "intermittent fasting": [
        "intermittent fasting",
        "if",
        "16:8",
        "time-restricted eating",
    ],
    "artificial sweeteners": [
        "artificial sweeteners",
        "aspartame",
        "sucralose",
        "stevia",
        "saccharin",
        "diet soda",
    ],
    "added sugar": [
        "added sugar",
        "sugar",
        "refined sugar",
        "sucrose",
        "high fructose corn syrup",
    ],
    "dairy milk": ["milk", "dairy milk", "cow milk", "cow's milk"],
}

FUZZY_THRESHOLD = 85

# Precomputed: all aliases lowercased, mapped back to their canonical food.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias.lower().strip(): canonical
    for canonical, aliases in KNOWN_FOODS.items()
    for alias in aliases
}

# Short aliases (≤2 chars) are prone to substring false positives
# ("if" in "gift", "egg" in "leggings"). Exclude them from substring
# matching; they still match via the exact-alias path.
_SUBSTRING_MIN_LEN = 3


def normalize_food(raw: str) -> tuple[str, bool]:
    """Normalize a raw food name to a canonical form.

    Returns ``(canonical_name, is_in_known_list)``. For unknown foods
    the canonical_name is the lowercased/stripped input.
    """
    if not raw:
        return ("", False)

    key = raw.lower().strip()
    if not key:
        return ("", False)

    if key in _ALIAS_TO_CANONICAL:
        return (_ALIAS_TO_CANONICAL[key], True)

    substring_match = _substring_match(key)
    if substring_match is not None:
        return (substring_match, True)

    fuzzy_match = _fuzzy_match(key)
    if fuzzy_match is not None:
        return (fuzzy_match, True)

    return (key, False)


def _substring_match(key: str) -> str | None:
    """Return the canonical name whose alias appears as a whole word in ``key``.

    Longer aliases win to avoid "red meat" → "meat" type collisions.
    """
    best_alias: str | None = None
    for alias in _ALIAS_TO_CANONICAL:
        if len(alias) < _SUBSTRING_MIN_LEN:
            continue
        if _contains_as_phrase(key, alias):
            if best_alias is None or len(alias) > len(best_alias):
                best_alias = alias
    if best_alias is None:
        return None
    return _ALIAS_TO_CANONICAL[best_alias]


def _contains_as_phrase(haystack: str, needle: str) -> bool:
    """Whole-phrase containment: needle bordered by start/end or non-word chars."""
    idx = haystack.find(needle)
    while idx != -1:
        before_ok = idx == 0 or not haystack[idx - 1].isalnum()
        end = idx + len(needle)
        after_ok = end == len(haystack) or not haystack[end].isalnum()
        if before_ok and after_ok:
            return True
        idx = haystack.find(needle, idx + 1)
    return False


def _fuzzy_match(key: str) -> str | None:
    """Fuzzy-match against aliases using edit-distance ratio."""
    result = process.extractOne(
        key,
        list(_ALIAS_TO_CANONICAL.keys()),
        scorer=fuzz.ratio,
        score_cutoff=FUZZY_THRESHOLD,
    )
    if result is None:
        return None
    matched_alias, _score, _idx = result
    return _ALIAS_TO_CANONICAL[matched_alias]
