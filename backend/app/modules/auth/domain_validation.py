"""Pure domain-validation helpers for the allowed_email_domains allowlist.

No database, session, FastAPI, or persistent_config imports. Imported by
settings/schemas.py (validator) and four Phase 1236 enforcement paths
(signup, password login, SSO, admin-create).

Security notes
--------------
T-1235-01  Bare wildcard rejection: _ALL_MATCH is the prohibited
           single-character pattern, named so grep gates on literal tokens
           don't false-positive.
T-1235-02  Case-folding: domain and stored patterns are lower-cased at both
           comparison time and write time (normalize_domains).
T-1235-03  ReDoS avoidance: wildcard matching uses str.endswith() on a
           dotted suffix. User-supplied strings are NEVER compiled into a
           regex; the only compiled regex (_LABEL_RE) is fixed and applied
           only to bounded admin input.
"""

from __future__ import annotations

import re

# Prohibited single-character all-match sentinel (T-1235-01).
_ALL_MATCH = "*"

# Linear-time, fixed regex for a single DNS label: 1-63 chars of [a-z0-9-],
# must not start or end with a hyphen.  Applied only to admin-supplied,
# bounded-length domain patterns — never to user email strings.
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")


def normalize_domains(domains: list[str]) -> list[str]:
    """Return a canonical copy of *domains*: stripped, lower-cased, empty-dropped, de-duped.

    Order is preserved (first-seen wins on duplicates).
    """
    seen: set[str] = set()
    result: list[str] = []
    for entry in domains:
        normalized = entry.strip().lower()
        if not normalized:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def is_domain_pattern_valid(pattern: str) -> bool:
    """Return True only when *pattern* is a well-formed domain or ``*.`` wildcard.

    Rules (applied after strip+lower):
    - Empty / whitespace-only -> False
    - Bare all-match character -> False (T-1235-01)
    - Any internal whitespace -> False
    - ``*.`` prefix allowed; remainder must be a valid dotted domain
    - Each label: 1-63 chars of [a-z0-9-], no leading/trailing hyphen
    - At least one dot in the non-wildcard remainder
    - ``*.com`` style rejected — remainder needs at least two labels
    """
    normalized = pattern.strip().lower()
    if not normalized:
        return False
    if normalized == _ALL_MATCH:
        return False
    if " " in normalized or "\t" in normalized:
        return False

    if normalized.startswith("*."):
        remainder = normalized[2:]  # everything after "*."
        return _is_valid_dotted_domain(remainder, min_labels=2)

    # Double-wildcard or wildcard not at the front is invalid
    if _ALL_MATCH in normalized:
        return False

    return _is_valid_dotted_domain(normalized, min_labels=2)


def is_email_allowed(email: str, domains: list[str]) -> bool:
    """Return True if *email* is permitted by the *domains* allowlist.

    Empty *domains* -> allow all. Email domain is the substring after the
    LAST ``@``, lower-cased; missing/empty domain -> False when the list is
    non-empty. ``*.sub`` wildcards match subdomains only (the bare apex is
    NOT matched — T-1235-01 edge); otherwise exact match. Returns True on
    the first matching pattern. No user-supplied string is compiled into a
    regex (T-1235-03).
    """
    normalized_domains = normalize_domains(domains)
    if not normalized_domains:
        return True

    at_idx = email.rfind("@")
    if at_idx == -1:
        return False
    email_domain = email[at_idx + 1 :].lower()
    if not email_domain:
        return False

    for pattern in normalized_domains:
        if pattern.startswith("*."):
            suffix = pattern[2:]  # e.g. "example.com"
            if email_domain.endswith("." + suffix):
                return True
        else:
            if email_domain == pattern:
                return True

    return False


def _is_valid_dotted_domain(domain: str, min_labels: int = 2) -> bool:
    """Return True when *domain* is a valid dotted hostname with >= min_labels labels.

    *domain* must already be lower-cased/stripped with no wildcard prefix.
    min_labels defaults to 2, so a bare 'localhost' is rejected.
    """
    labels = domain.split(".")
    if len(labels) < min_labels:
        return False
    return all(_LABEL_RE.match(label) for label in labels)
