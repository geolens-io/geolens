"""Unit tests for the pure domain_validation helper.

All tests are sync and dependency-free — the helper has no DB/session/FastAPI imports.
"""

from app.modules.auth.domain_validation import (
    is_domain_pattern_valid,
    is_email_allowed,
    normalize_domains,
)


# ---------------------------------------------------------------------------
# normalize_domains
# ---------------------------------------------------------------------------


class TestNormalizeDomains:
    def test_lowercases_entries(self):
        result = normalize_domains(["EXAMPLE.COM"])
        assert result == ["example.com"]

    def test_strips_whitespace(self):
        result = normalize_domains([" sub.Example.com "])
        assert result == ["sub.example.com"]

    def test_deduplicates_preserving_order(self):
        result = normalize_domains(["EXAMPLE.COM", " sub.Example.com ", "example.com"])
        assert result == ["example.com", "sub.example.com"]

    def test_drops_empty_strings(self):
        result = normalize_domains(["", "example.com", "  "])
        assert result == ["example.com"]

    def test_empty_input(self):
        assert normalize_domains([]) == []

    def test_preserves_wildcard_prefix(self):
        result = normalize_domains(["*.EXAMPLE.COM"])
        assert result == ["*.example.com"]


# ---------------------------------------------------------------------------
# is_domain_pattern_valid
# ---------------------------------------------------------------------------


class TestIsDomainPatternValid:
    def test_plain_domain_valid(self):
        assert is_domain_pattern_valid("example.com") is True

    def test_subdomain_valid(self):
        assert is_domain_pattern_valid("mail.example.com") is True

    def test_wildcard_subdomain_valid(self):
        assert is_domain_pattern_valid("*.example.com") is True

    def test_bare_wildcard_invalid(self):
        # T-1235-01: bare wildcard = match-everything, must be rejected
        assert is_domain_pattern_valid("*") is False

    def test_empty_string_invalid(self):
        assert is_domain_pattern_valid("") is False

    def test_whitespace_only_invalid(self):
        assert is_domain_pattern_valid("   ") is False

    def test_space_inside_invalid(self):
        assert is_domain_pattern_valid("no spaces allowed.com") is False

    def test_label_starting_with_hyphen_invalid(self):
        assert is_domain_pattern_valid("-bad.com") is False

    def test_label_ending_with_hyphen_invalid(self):
        assert is_domain_pattern_valid("bad-.com") is False

    def test_single_label_no_dot_invalid(self):
        # Single label like 'localhost' has no dot — rejected (admins configure registered domains)
        assert is_domain_pattern_valid("localhost") is False

    def test_numeric_labels_valid(self):
        assert is_domain_pattern_valid("example123.co.uk") is True

    def test_wildcard_single_label_remainder_invalid(self):
        # *.com would match *.com — remainder 'com' has no dot, rejected
        assert is_domain_pattern_valid("*.com") is False

    def test_mixed_case_normalized_and_valid(self):
        # The function strips+lowers before checking
        assert is_domain_pattern_valid("EXAMPLE.COM") is True

    def test_double_wildcard_invalid(self):
        assert is_domain_pattern_valid("*.*.example.com") is False


# ---------------------------------------------------------------------------
# is_email_allowed
# ---------------------------------------------------------------------------


class TestIsEmailAllowed:
    def test_empty_domains_allows_all(self):
        """Empty domain list means unrestricted (allow-all)."""
        assert is_email_allowed("a@example.com", []) is True

    def test_exact_match(self):
        assert is_email_allowed("a@example.com", ["example.com"]) is True

    def test_exact_no_match(self):
        assert is_email_allowed("a@example.com", ["other.com"]) is False

    def test_case_fold_email(self):
        """T-1235-02: Mixed-case email domain must be folded before comparison."""
        assert is_email_allowed("A@EXAMPLE.COM", ["example.com"]) is True

    def test_case_fold_pattern(self):
        """Stored patterns are case-folded; comparison remains case-insensitive."""
        assert is_email_allowed("a@example.com", ["EXAMPLE.COM"]) is True

    def test_wildcard_subdomain_match(self):
        assert is_email_allowed("a@mail.example.com", ["*.example.com"]) is True

    def test_wildcard_apex_excluded(self):
        """Wildcard matches subdomains only — apex must be listed explicitly."""
        assert is_email_allowed("a@example.com", ["*.example.com"]) is False

    def test_wildcard_multi_level_subdomain(self):
        """*.example.com must match deep.mail.example.com too."""
        assert is_email_allowed("a@deep.mail.example.com", ["*.example.com"]) is True

    def test_no_at_sign_not_allowed(self):
        """No '@' in email -> no domain -> not allowed against a non-empty list."""
        assert is_email_allowed("not-an-email", ["example.com"]) is False

    def test_multiple_at_signs_uses_last(self):
        """Domain is the substring after the LAST '@'."""
        assert is_email_allowed("a@b@example.com", ["example.com"]) is True

    def test_empty_domain_after_at_not_allowed(self):
        assert is_email_allowed("user@", ["example.com"]) is False

    def test_multiple_domains_first_match_wins(self):
        assert is_email_allowed("a@example.com", ["other.com", "example.com"]) is True

    def test_multiple_domains_no_match(self):
        assert is_email_allowed("a@example.com", ["other.com", "third.com"]) is False
