"""Score AI metadata drafts for claims their context does not support.

Shared by the live grounding evals and the prompt unit tests. A draft passes
when every sentence that makes a claim of an unsupported kind carries the
``(inferred)`` marker. The patterns are deliberately narrow: they catch the
claims a synthetic fixture with no dates, no publisher and no stated purpose
cannot support, not every possible overreach.
"""

import re

INFERRED_MARKER = "(inferred)"

# Kinds of claim the parks fixture gives no evidence for.
UNSUPPORTED_CLAIMS: dict[str, re.Pattern[str]] = {
    "time": re.compile(
        r"\b(1[89]\d{2}|20\d{2})\b"
        r"|\b(current|currently|up[- ]to[- ]date|recent|recently|as of|updated|"
        r"latest|historical)\b",
        re.IGNORECASE,
    ),
    "audience": re.compile(
        r"\b(planners?|residents?|researchers?|analysts?|officials?|stakeholders?|"
        r"policymakers?|decision[- ]makers?|citizens?|practitioners?|"
        r"professionals?|users?|audiences?)\b",
        re.IGNORECASE,
    ),
    "use": re.compile(
        r"\b(suitable for|useful for|used for|can be used|could be used|may be used|"
        r"ideal for|valuable for|supports?|supporting|enables?|planning|"
        r"decision[- ]making|applications?)\b",
        re.IGNORECASE,
    ),
    "publisher": re.compile(
        r"\b(department|agency|authority|maintained by|published by|provided by|"
        r"produced by|compiled by|created by|NYC Parks|DPR)\b",
        re.IGNORECASE,
    ),
    "processing": re.compile(
        r"\b(cleaned|validated|filtered|deduplicated|quality[- ]controlled|"
        r"digitized|digitised|surveyed|collected|field[- ]verified)\b",
        re.IGNORECASE,
    ),
    "accuracy": re.compile(
        r"\b(accurate to|accuracy of|positional accuracy is|highly accurate|"
        r"high accuracy|highly precise|precise to|authoritative)\b",
        re.IGNORECASE,
    ),
}

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def unsupported_claims(draft: str, kinds: tuple[str, ...]) -> list[tuple[str, str]]:
    """``(kind, sentence)`` for each unmarked sentence making a ``kinds`` claim."""
    found = []
    for sentence in _SENTENCE.split(draft.strip()):
        if INFERRED_MARKER in sentence.lower():
            continue
        for kind in kinds:
            if UNSUPPORTED_CLAIMS[kind].search(sentence):
                found.append((kind, sentence))
    return found


# Places the fixture's extent and sample values identify, and their parents.
GROUNDED_PLACES = frozenset(
    {
        "new york",
        "new york city",
        "nyc",
        "manhattan",
        "brooklyn",
        "queens",
        "bronx",
        "the bronx",
        "staten island",
        "new york state",
        "united states",
        "usa",
        "north america",
    }
)


def _grounded_place(keyword: str) -> bool:
    # A combined keyword such as "bronx and staten island" names grounded places.
    parts = re.split(r",|\band\b", keyword.lower())
    return all(part.strip() in GROUNDED_PLACES for part in parts if part.strip())


def ungrounded_keywords(keywords: list[dict]) -> list[dict]:
    """Keywords naming a time or a place the fixture does not support."""
    return [
        kw
        for kw in keywords
        if kw["keyword_type"] == "temporal"
        or (kw["keyword_type"] == "place" and not _grounded_place(kw["keyword"]))
    ]
