"""WR-02: Audit service _apply_filters resource_type.ilike must escape %, _, and \\.

The _apply_filters() function in audit/service.py passed the raw user-supplied
search string into AuditLog.resource_type.ilike(f"%{search}%") without escaping
special ILIKE characters. An admin searching for "%" would receive all rows
(pattern "%%") regardless of resource_type.

Fix: escape_ilike() is applied before composing the pattern, and escape="\\"
is passed to ilike() to make the ESCAPE character explicit in the emitted SQL.

This file contains:
  - TestAuditEscapeIlikeSql:  SQL compilation unit tests (no DB required).
    These inspect the compiled WHERE clause to confirm the escape contract is
    honoured at the SQLAlchemy level without spinning up a database.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.modules.audit.models import AuditLog
from app.modules.audit.service import _apply_filters


def _compile_query(q) -> str:
    """Return the compiled SQL string for a SQLAlchemy select statement."""
    return str(q.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class TestAuditEscapeIlikeSql:
    """SQL-compilation unit tests for WR-02.

    These verify that the emitted SQL contains the correct escaped patterns and
    the ESCAPE clause, without requiring a live database connection.
    """

    def _base(self):
        return select(AuditLog)

    def test_percent_literal_escaped_in_resource_type_ilike(self):
        """search='%' must emit '\\%' in the resource_type ILIKE pattern, not '%%'."""
        q = _apply_filters(self._base(), search="%")
        sql = _compile_query(q)
        # The resource_type ILIKE branch must contain the escaped percent
        assert r"\%" in sql, (
            f"Expected escaped percent '\\%' in SQL, got:\n{sql}"
        )
        # Must NOT contain a bare '%%' pattern (which would match all rows)
        assert "'%%" not in sql and "= '%%'" not in sql, (
            f"Bare '%%' pattern found in SQL — percent is acting as wildcard:\n{sql}"
        )

    def test_underscore_literal_escaped_in_resource_type_ilike(self):
        """search='_' must emit '\\_' in the resource_type ILIKE pattern."""
        q = _apply_filters(self._base(), search="_")
        sql = _compile_query(q)
        assert r"\_" in sql, (
            f"Expected escaped underscore '\\_' in SQL, got:\n{sql}"
        )

    def test_backslash_literal_doubled_in_resource_type_ilike(self):
        """search='\\\\' (literal backslash) must emit '\\\\\\\\' in the SQL pattern."""
        q = _apply_filters(self._base(), search="\\")
        sql = _compile_query(q)
        # A doubled backslash in the ILIKE pattern (PostgreSQL escaping on top)
        assert "\\\\" in sql, (
            f"Expected doubled backslash in SQL pattern, got:\n{sql}"
        )

    def test_escape_clause_present(self):
        """The ILIKE call must emit ESCAPE '\\\\' to make the escape char explicit."""
        q = _apply_filters(self._base(), search="anything")
        sql = _compile_query(q)
        # SQLAlchemy emits ESCAPE '\\' when escape="\\" is passed
        assert "ESCAPE" in sql.upper(), (
            f"Expected ESCAPE clause in SQL for resource_type ilike, got:\n{sql}"
        )

    def test_plain_text_search_unaffected(self):
        """Normal text without special chars passes through without modification."""
        q = _apply_filters(self._base(), search="dataset")
        sql = _compile_query(q)
        assert "dataset" in sql, f"Expected 'dataset' in SQL, got:\n{sql}"

    def test_no_search_adds_no_filter(self):
        """search=None must not add any WHERE clause."""
        base = self._base()
        q = _apply_filters(base, search=None)
        sql = _compile_query(q)
        assert "WHERE" not in sql, (
            f"search=None should not add WHERE clause, got:\n{sql}"
        )
