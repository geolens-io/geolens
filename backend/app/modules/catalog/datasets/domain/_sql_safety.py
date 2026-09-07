"""SQL identifier safety helpers.

Single source of truth for SQL-injection-prevention regexes used across the
dataset domain sub-modules: SAFE_TABLE_NAME_RE (lowercase ingestion-path
table/schema names) and SAFE_COLUMN_NAME_RE (standard SQL identifiers).
"""

from __future__ import annotations

import re

SAFE_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
SAFE_COLUMN_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _safe_table_ref(table_name: str, schema: str = "data") -> str:
    """Return a safely quoted ``"<schema>"."<name>"`` SQL identifier.

    Validates both table_name and schema against SAFE_TABLE_NAME_RE before
    interpolating into DDL that cannot use bound parameters (T-1209-05).
    Multi-tenant callers pass the per-tenant schema from
    tenant_data_schema(tid); it matches the same lowercase pattern.

    Raises
    ------
    ValueError
        If table_name or schema fails validation.
    """
    if not SAFE_TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")
    if not SAFE_TABLE_NAME_RE.match(schema):
        raise ValueError(f"Invalid schema name: {schema!r}")
    return f'"{schema}"."{table_name}"'


def _safe_column_ref(name: str) -> str:
    """Return a double-quoted column identifier for use inside ``text()``.

    fix(#1778): quotes so a reserved-word column name (``desc``, ``order`` --
    routine ogr2ogr/DBF output) doesn't break the SQL. Embedded quotes are
    doubled; colons are backslash-escaped since SQLAlchemy ``text()`` reads
    ``:name`` as a bind parameter even inside a quoted identifier. Not a
    substitute for validation -- callers still filter through SAFE_*_RE first.
    """
    return '"' + name.replace('"', '""').replace(":", "\\:") + '"'
