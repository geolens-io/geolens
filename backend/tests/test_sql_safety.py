"""Unit tests for SQL identifier safety helpers.

These helpers prevent SQL injection by validating and quoting table names
used in dynamic DDL/DML statements.
"""

import pytest

from app.datasets.service import _safe_table_ref
from app.ingest.metadata import _qtable, _validate_table_name


class TestValidateTableName:
    def test_valid_lowercase(self):
        _validate_table_name("my_table")

    def test_valid_with_digits(self):
        _validate_table_name("table_123")

    def test_valid_underscore_prefix(self):
        _validate_table_name("_leading_underscore")

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table_name("MyTable")

    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table_name("test'; DROP TABLE users; --")

    def test_rejects_semicolon(self):
        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table_name("table;drop")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table_name("table name")

    def test_rejects_double_quotes(self):
        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table_name('table"name')

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table_name("")

    def test_rejects_dots(self):
        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table_name("schema.table")

    def test_rejects_hyphens(self):
        with pytest.raises(ValueError, match="Invalid table name"):
            _validate_table_name("my-table")


class TestQtable:
    def test_returns_quoted_identifier(self):
        assert _qtable("my_table") == '"data"."my_table"'

    def test_rejects_invalid_name(self):
        with pytest.raises(ValueError):
            _qtable("bad; DROP TABLE")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _qtable("")


class TestSafeTableRef:
    def test_returns_quoted_identifier(self):
        assert _safe_table_ref("my_table") == '"data"."my_table"'

    def test_rejects_invalid_name(self):
        with pytest.raises(ValueError):
            _safe_table_ref("bad; DROP TABLE")

    def test_rejects_double_quotes(self):
        with pytest.raises(ValueError):
            _safe_table_ref('escape"attempt')

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            _safe_table_ref("")

    def test_accepts_underscore_and_digits(self):
        assert _safe_table_ref("table_123_abc") == '"data"."table_123_abc"'
