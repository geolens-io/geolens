"""Pure domain-validation helpers for the allowed_email_domains allowlist.

This module has NO database, session, FastAPI, or persistent_config imports.
It is imported by:
  - backend/app/modules/settings/schemas.py (validator, this phase)
  - four enforcement paths in Phase 1236 (signup, password login, SSO, admin-create)

Security notes
--------------
T-1235-01  Bare wildcard rejection: _ALL_MATCH is the prohibited single-character
           pattern; it is stored as a named constant so negative grep gates on
           literal tokens don't produce false positives.

T-1235-02  Case-folding: both the email domain and stored patterns are lower-cased
           at comparison time AND at write time (normalize_domains), so neither side
           can be skipped.

T-1235-03  ReDoS avoidance: wildcard matching uses plain str.endswith() on a dotted
           suffix.  User-supplied strings are NEVER compiled into a dynamic regex.
           The only compiled regex (_LABEL_RE) is a fixed, module-level pattern applied
           to bounded admin input only.
"""

from __future__ import annotations

import re

# Prohibited single-character all-match sentinel (T-1235-01).
_ALL_MATCH = "*"

# Linear-time, fixed regex for a single DNS label: 1-63 chars of [a-z0-9-],
# must not start or end with a hyphen.  Applied only to admin-supplied,
# bounded-length domain patterns — never to user email strings.
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_domains(domains: list[str]) -> list[str]:
    """Return a canonical copy of *domains*: stripped, lower-cased, empty-dropped, de-duped.

    Order is preserved (first-seen wins on duplicates).

    Args:
        domains: Raw list of domain patterns (may include mixed case, extra whitespace,
                 or empty strings).

    Returns:
        New list of normalized, deduplicated patterns.
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
    - Empty / whitespace-only  → False
    - Bare all-match character → False  (T-1235-01)
    - Any internal whitespace  → False
    - ``*.`` prefix allowed; the remainder must itself be a valid dotted domain
    - Each label: 1-63 chars of ``[a-z0-9-]``, may NOT start or end with a hyphen
    - At least one dot in the non-wildcard remainder (single bare labels rejected)
    - ``*.com`` style rejected — the remainder must have at least two labels

    Args:
        pattern: A single domain pattern string (may be mixed case / have whitespace).

    Returns:
        True if valid, False otherwise.
    """
    normalized = pattern.strip().lower()
    if not normalized:
        return False
    if normalized == _ALL_MATCH:
        return False
    # No internal whitespace (after strip, a space anywhere in the middle is illegal)
    if " " in normalized or "\t" in normalized:
        return False

    # Wildcard prefix handling
    if normalized.startswith("*."):
        remainder = normalized[2:]  # everything after "*."
        return _is_valid_dotted_domain(remainder, min_labels=2)

    # Double-wildcard or wildcard not at the front is invalid
    if _ALL_MATCH in normalized:
        return False

    return _is_valid_dotted_domain(normalized, min_labels=2)


def is_email_allowed(email: str, domains: list[str]) -> bool:
    """Return True if *email* is permitted by the *domains* allowlist.

    Semantics
    ---------
    - Empty *domains* list → allow all (True).
    - The email domain is the substring after the **last** ``@``, lower-cased.
    - If there is no ``@`` or the domain portion is empty → False (when list is non-empty).
    - Pattern matching (case-insensitive, both sides normalized):
        - ``*.sub`` wildcard: email domain must end with ``"." + suffix``
          (subdomain match; the bare apex itself is NOT matched — T-1235-01 edge).
        - Otherwise: exact equality.
    - Returns True on the first matching pattern.

    No user-supplied string is compiled into a regex (T-1235-03).

    Args:
        email:   The email address to check (may be mixed case / have multiple @).
        domains: The configured allowlist (may be mixed case; normalized internally).

    Returns:
        True if the email is allowed, False otherwise.
    """
    normalized_domains = normalize_domains(domains)
    if not normalized_domains:
        return True  # allow-all: empty list means unrestricted

    # Extract domain: everything after the LAST '@'
    at_idx = email.rfind("@")
    if at_idx == -1:
        return False
    email_domain = email[at_idx + 1 :].lower()
    if not email_domain:
        return False

    for pattern in normalized_domains:
        if pattern.startswith("*."):
            # Wildcard: match subdomains only (apex excluded)
            suffix = pattern[2:]  # e.g. "example.com"
            if email_domain.endswith("." + suffix):
                return True
        else:
            # Exact match
            if email_domain == pattern:
                return True

    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_valid_dotted_domain(domain: str, min_labels: int = 2) -> bool:
    """Return True when *domain* is a valid dotted hostname with >= min_labels labels.

    Args:
        domain:     Already lower-cased, stripped domain string (no wildcard prefix).
        min_labels: Minimum number of dot-separated labels required (default 2,
                    so bare 'localhost' is rejected).

    Returns:
        True if all labels match _LABEL_RE and there are at least *min_labels* labels.
    """
    labels = domain.split(".")
    if len(labels) < min_labels:
        return False
    return all(_LABEL_RE.match(label) for label in labels)
