"""Tests for the AST-based WHERE-clause validator (SEC-S09).

Tests are grouped into:
  - test_allowlist_*  : expressions that MUST pass validate_where_ast()
  - test_blocklist_*  : expressions that MUST raise ValueError
  - test_wrapper_*    : integration tests for validate_where_clause (service layer)
  - test_endpoint_*   : HTTP-level tests against the export endpoint (require DB + live fixture)

Endpoint tests require a running DB and use the httpx AsyncClient from conftest.
They are skipped automatically when SEC_AUDIT_PUBLIC_DATASET_ID is not set.
"""

from __future__ import annotations

import pytest

from app.processing.export.where_validator import validate_where_ast
from app.processing.export.service import validate_where_clause


# ─────────────────────────────────────────────────────────────────────────────
# Allowlist — these must pass (return None)
# ─────────────────────────────────────────────────────────────────────────────


class TestAllowlist:
    def test_allowlist_simple_gt(self):
        assert validate_where_ast("gid > 100") is None

    def test_allowlist_combined_and(self):
        assert validate_where_ast("state = 'CA' AND pop < 5000") is None

    def test_allowlist_like(self):
        assert validate_where_ast("name LIKE 'A%'") is None

    def test_allowlist_in_list(self):
        assert validate_where_ast("category IN ('a', 'b', 'c')") is None

    def test_allowlist_between(self):
        assert validate_where_ast("created_at BETWEEN '2024-01-01' AND '2024-12-31'") is None

    def test_allowlist_is_null(self):
        assert validate_where_ast("col IS NULL") is None

    def test_allowlist_is_not_null(self):
        assert validate_where_ast("col IS NOT NULL") is None

    def test_allowlist_complex_logical(self):
        assert validate_where_ast("(a > 1 OR b < 2) AND NOT c = 'x'") is None

    def test_allowlist_negative_number(self):
        """Unary minus on a numeric literal must pass."""
        assert validate_where_ast("score > -5") is None

    def test_allowlist_string_with_escaped_quote(self):
        """SQL single-quote escaping inside a string literal must pass."""
        assert validate_where_ast("name = 'O''Brien'") is None

    def test_allowlist_double_negation(self):
        assert validate_where_ast("NOT NOT (a > 1)") is None

    def test_allowlist_deeply_nested_parens(self):
        assert validate_where_ast("((((a > 1))))") is None

    def test_allowlist_mixed_case_keywords(self):
        """Keyword case variations must not affect allowlist evaluation."""
        assert validate_where_ast("a IN (1, 2) AND b BETWEEN 0 AND 10") is None

    def test_allowlist_neq_operator(self):
        assert validate_where_ast("status != 'inactive'") is None

    def test_allowlist_gte_and_lte(self):
        assert validate_where_ast("score >= 10 AND score <= 100") is None

    def test_allowlist_in_numeric_list(self):
        assert validate_where_ast("gid IN (1, 2, 3)") is None

    def test_allowlist_multiple_and_or(self):
        assert validate_where_ast("a > 1 AND b > 2 AND c > 3 OR d = 'x'") is None

    def test_allowlist_bool_column(self):
        """Boolean column comparison."""
        assert validate_where_ast("active = true") is None


# ─────────────────────────────────────────────────────────────────────────────
# Blocklist — these must raise ValueError
# ─────────────────────────────────────────────────────────────────────────────


class TestBlocklist:
    def test_blocklist_union_attack(self):
        """UNION grammar must be rejected as multi-statement / non-Select root."""
        with pytest.raises(ValueError, match="WHERE expression"):
            validate_where_ast("gid > 0 UNION SELECT 1, 2, 3")

    def test_blocklist_subquery_in(self):
        """Subquery inside IN clause must be rejected."""
        with pytest.raises(ValueError):
            validate_where_ast("gid IN (SELECT id FROM users)")

    def test_blocklist_subquery_exists(self):
        """EXISTS subquery must be rejected."""
        with pytest.raises(ValueError):
            validate_where_ast("EXISTS (SELECT 1 FROM users WHERE 1=1)")

    def test_blocklist_function_pg_sleep(self):
        with pytest.raises(ValueError):
            validate_where_ast("pg_sleep(10)")

    def test_blocklist_function_pg_read_file(self):
        with pytest.raises(ValueError):
            validate_where_ast("pg_read_file('/etc/passwd') IS NOT NULL")

    def test_blocklist_function_lower(self):
        """Even 'safe' function calls like lower() are rejected (strict allowlist)."""
        with pytest.raises(ValueError):
            validate_where_ast("lower(name) = 'x'")

    def test_blocklist_function_length(self):
        with pytest.raises(ValueError):
            validate_where_ast("length(name) > 5")

    def test_blocklist_multi_statement_drop(self):
        """Semicolon multi-statement with DDL must be rejected."""
        with pytest.raises(ValueError, match="WHERE expression|syntax"):
            validate_where_ast("1=1; DROP TABLE users; --")

    def test_blocklist_multi_statement_select(self):
        with pytest.raises(ValueError, match="WHERE expression|syntax"):
            validate_where_ast("1=1; SELECT 1")

    def test_blocklist_empty_string(self):
        with pytest.raises(ValueError, match="Empty WHERE expression"):
            validate_where_ast("")

    def test_blocklist_blank_whitespace(self):
        with pytest.raises(ValueError, match="Empty WHERE expression"):
            validate_where_ast("   ")

    def test_blocklist_invalid_syntax(self):
        """Invalid SQL syntax must raise ValueError."""
        with pytest.raises(ValueError):
            validate_where_ast("'; --")

    def test_blocklist_select_as_where(self):
        """A bare SELECT statement cannot serve as a WHERE expression."""
        with pytest.raises(ValueError):
            validate_where_ast("SELECT 1")

    def test_blocklist_union_intersect(self):
        """INTERSECT must also be caught as set-operation grammar."""
        with pytest.raises(ValueError):
            validate_where_ast("gid > 0 INTERSECT SELECT 1")

    def test_blocklist_subquery_scalar(self):
        """Scalar subquery must be rejected."""
        with pytest.raises(ValueError):
            validate_where_ast("gid = (SELECT MAX(gid) FROM data)")

    def test_blocklist_function_coalesce(self):
        """COALESCE is a function — must be rejected by strict allowlist."""
        with pytest.raises(ValueError):
            validate_where_ast("COALESCE(col, 0) > 1")

    def test_table_qualified_reference_rejected(self):
        """Pins the KNOWN-10 fix: sqlglot's postgres dialect parses tbl.col
        into exp.Column with .table populated (not a separate exp.Dot node).
        validate_where_ast inspects Column.table/.db/.catalog and raises
        with the 'table-qualified column reference' message.

        CR-03 (Phase 1071 review): removed the dead 'Dot' branch from the
        assertion — the validator uses Column.table inspection so 'Dot' never
        appears in the error message. Assert the exact rejection string instead.
        KNOWN-10 (v1062 IN-03)."""
        with pytest.raises(ValueError) as exc:
            validate_where_ast("catalog.records.title = 'x'")
        # Error message names the table-qualified rejection specifically.
        assert "table-qualified" in str(exc.value).lower() or "Disallowed" in str(exc.value)

        # Two-segment table.column form (the more common attack shape).
        with pytest.raises(ValueError):
            validate_where_ast("records.title = 'x'")


# ─────────────────────────────────────────────────────────────────────────────
# Wrapper integration — validate_where_clause (service.py)
# ─────────────────────────────────────────────────────────────────────────────


class TestWrapper:
    _COL_INFO = [{"name": "pop"}, {"name": "gid"}, {"name": "state"}]

    def test_wrapper_happy_path_still_works(self):
        """validate_where_clause with a valid expression returns the expression unchanged."""
        result = validate_where_clause("pop > 1000", column_info=self._COL_INFO)
        assert result == "pop > 1000"

    def test_wrapper_calls_ast_validator_first(self):
        """UNION attack must be rejected by the AST gate before identifier check."""
        with pytest.raises(ValueError) as exc_info:
            validate_where_clause(
                "gid > 0 UNION SELECT 1",
                column_info=self._COL_INFO,
            )
        # Error message should come from the AST validator, not the identifier check
        msg = str(exc_info.value).lower()
        assert "where expression" in msg or "select" in msg or "disallowed" in msg
        assert "unknown column" not in msg

    def test_wrapper_unknown_column_still_caught(self):
        """AST passes for valid-syntax-but-unknown-column; identifier check catches it."""
        with pytest.raises(ValueError, match="Unknown column: foo"):
            validate_where_clause("foo > 1000", column_info=[{"name": "pop"}])

    def test_wrapper_no_column_info_rejected(self):
        with pytest.raises(ValueError, match="Cannot filter"):
            validate_where_clause("pop > 1000", column_info=None)

    def test_wrapper_subquery_rejected_before_identifier_check(self):
        """Subquery must be rejected by AST gate, not identifier loop."""
        with pytest.raises(ValueError) as exc_info:
            validate_where_clause(
                "gid IN (SELECT id FROM users)",
                column_info=self._COL_INFO,
            )
        assert "unknown column" not in str(exc_info.value).lower()

    def test_wrapper_function_call_rejected_before_identifier_check(self):
        with pytest.raises(ValueError) as exc_info:
            validate_where_clause("pg_sleep(10)", column_info=self._COL_INFO)
        assert "unknown column" not in str(exc_info.value).lower()

    def test_wrapper_empty_column_info_list_rejected(self):
        """Empty list is falsy — treated the same as None."""
        with pytest.raises(ValueError, match="Cannot filter"):
            validate_where_clause("pop > 1000", column_info=[])


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint-level HTTP tests (require running DB + SEC_AUDIT_PUBLIC_DATASET_ID)
#
# Fixture-provisioning recipe:
#   1. Start the stack: docker compose up -d db api worker
#   2. In the UI (or via API), create/import a small public dataset with a
#      numeric column (e.g. "gid") and note the public_id UUID.
#   3. Export SEC_AUDIT_PUBLIC_DATASET_ID=<uuid> in your shell.
#   4. Re-run: cd backend && pytest tests/test_export_where_validator.py -k "endpoint"
#
# These tests are skipped automatically when the env var is not set so the
# full test suite remains runnable in CI without fixtures.
# ─────────────────────────────────────────────────────────────────────────────


import os
import urllib.parse


class TestEndpoint:
    """HTTP-level regression tests for the export -where gate (SEC-S09).

    Requires a live API (httpx AsyncClient from conftest) + a real public dataset.
    Skipped when SEC_AUDIT_PUBLIC_DATASET_ID is not set.
    """

    @pytest.fixture(autouse=True)
    def require_dataset_id(self):
        dataset_id = os.environ.get("SEC_AUDIT_PUBLIC_DATASET_ID")
        if not dataset_id:
            pytest.skip("Set SEC_AUDIT_PUBLIC_DATASET_ID to a public exportable dataset")
        self.dataset_id = dataset_id

    @pytest.mark.anyio
    async def test_endpoint_rejects_union_attack(self, client, admin_auth_header):
        """GET /datasets/{id}/export?where=<UNION> must return 400."""
        payload = "gid > 0 UNION SELECT 1, 2, 3"
        encoded = urllib.parse.quote_plus(payload)
        resp = await client.get(
            f"/datasets/{self.dataset_id}/export",
            params={"format": "csv", "where": payload},
            headers=admin_auth_header,
        )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for UNION attack, got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.anyio
    async def test_endpoint_rejects_subquery(self, client, admin_auth_header):
        """GET /datasets/{id}/export?where=<subquery> must return 400."""
        resp = await client.get(
            f"/datasets/{self.dataset_id}/export",
            params={"format": "csv", "where": "gid IN (SELECT 1 FROM users)"},
            headers=admin_auth_header,
        )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for subquery, got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.anyio
    async def test_endpoint_rejects_function_call(self, client, admin_auth_header):
        """GET /datasets/{id}/export?where=pg_sleep(10) must return 400."""
        resp = await client.get(
            f"/datasets/{self.dataset_id}/export",
            params={"format": "csv", "where": "pg_sleep(10)"},
            headers=admin_auth_header,
        )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for function call, got {resp.status_code}: {resp.text}"
        )
