"""Unit tests for Phase 1069 export hardening:
- IA-P1-04: validate_where_clause rejects statement terminators, comments,
  and unbalanced single-quotes (in addition to v1014 SEC-S09 AST allowlist).
- IA-P1-01: export_dataset_endpoint depends on require_permission("export")
  instead of get_current_active_user, closing the capability-matrix gap.

Requirements: IA-P1-04, IA-P1-01
Phase: 1069
"""

import pytest

from app.processing.export.service import validate_where_clause


# ---------------------------------------------------------------------------
# IA-P1-04: where-clause rejects meta-SQL tokens
# ---------------------------------------------------------------------------


COLS = [{"name": "pop"}, {"name": "name"}, {"name": "country"}]


class TestWhereClauseInjectionRejection:
    def test_statement_terminator_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("pop > 1000; DROP TABLE catalog.records", COLS)
        assert "terminator" in str(exc.value).lower() or ";" in str(exc.value)

    def test_line_comment_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("pop > 1000 -- malicious", COLS)
        assert "comment" in str(exc.value).lower() or "--" in str(exc.value)

    def test_block_comment_open_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("pop > 1000 /* injection", COLS)
        assert "comment" in str(exc.value).lower() or "/*" in str(exc.value)

    def test_block_comment_close_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("name = */ 'x'", COLS)
        assert "comment" in str(exc.value).lower() or "*/" in str(exc.value)

    def test_unbalanced_quote_rejected(self):
        with pytest.raises(ValueError) as exc:
            validate_where_clause("name = 'a", COLS)
        assert "quote" in str(exc.value).lower()

    def test_classic_or_injection_blocked_by_ast(self):
        """The AST layer (v1014 SEC-S09) blocks UNION/subquery injection."""
        with pytest.raises(ValueError) as exc:
            validate_where_clause(
                "name = 'a' OR '1'='1' UNION SELECT password FROM users",
                COLS,
            )
        # Any layer (string-level or AST) is fine; just verify it's rejected.
        assert exc.value  # truthy

    def test_balanced_string_literal_accepted(self):
        """A legitimate WHERE with properly-quoted string literals passes the
        IA-P1-04 checks (statement terminator / comment / unbalanced quote)
        and the v1014 SEC-S09 AST allowlist.

        Note: the identifier regex inside validate_where_clause may flag
        text-inside-quotes as a candidate identifier (pre-existing v1014
        behavior, out of IA-P1-04 scope). To exercise just the IA-P1-04
        layer we use a quoted value that doesn't look like an identifier."""
        # Numeric-only string (passes identifier check, passes IA-P1-04).
        validate_where_clause("name = '42'", COLS)
        # SQL-escaped doubled quote — IA-P1-04 must accept (collapses to even).
        validate_where_clause("name = '42'' '", COLS)

    def test_numeric_comparison_accepted(self):
        validate_where_clause("pop > 1000", COLS)
        validate_where_clause("pop BETWEEN 100 AND 200", COLS)


# ---------------------------------------------------------------------------
# IA-P1-01: capability gate on export_dataset_endpoint
# ---------------------------------------------------------------------------


class TestExportEndpointCapabilityGate:
    def test_export_endpoint_uses_require_permission(self):
        """The dependency on the endpoint must be the require_permission
        factory for 'export', NOT bare get_current_active_user. This is a
        static-shape test that doesn't need a live FastAPI app."""
        import inspect

        from app.processing.export.router import export_dataset_endpoint
        from app.modules.auth.dependencies import require_permission

        sig = inspect.signature(export_dataset_endpoint)
        user_param = sig.parameters["user"]
        default = user_param.default

        # FastAPI Depends carries a `dependency` attribute that's the resolver.
        # require_permission("export") returns a closure named _permission_checker.
        assert default is not None, "user param must have a Depends() default"
        dep_callable = getattr(default, "dependency", None)
        assert dep_callable is not None, "Depends() must reference a callable"
        # The closure name from require_permission factory is _permission_checker.
        assert dep_callable.__name__ == "_permission_checker", (
            f"Expected require_permission factory, got {dep_callable.__name__}"
        )
