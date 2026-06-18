"""SQL identifier safety helpers (extracted from service.py — Phase 224 post-impl).

Single source of truth for SQL-injection-prevention regexes used by the dataset
domain sub-modules. Two distinct patterns exist:

- SAFE_TABLE_NAME_RE: lowercase-only table names produced by the ingestion path
  (e.g., "ds_abc123"). Used by service_lifecycle, service_metadata, service_query.
- SAFE_COLUMN_NAME_RE: standard SQL identifier (Python-identifier-style, mixed case).
  Used by service_create (column DDL) and service_relationships (FK column lookup).

Pre-Phase-224, the lowercase pattern was redefined in 5 places and the column-name
pattern in 2 places. Consolidating here removes drift risk and gives one audit
point for security-critical validation.
"""

from __future__ import annotations

import re

# Lowercase-only table names from the ingestion path. Anchored.
SAFE_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")

# Standard SQL identifier (Python-identifier-style). Anchored. Mixed case.
SAFE_COLUMN_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _safe_table_ref(table_name: str, schema: str = "data") -> str:
    """Return a safely quoted ``"<schema>"."<name>"`` SQL identifier.

    Validates ``table_name`` against ``SAFE_TABLE_NAME_RE`` and quotes the
    schema-qualified reference to prevent SQL injection in DDL statements
    (CREATE/DROP/ALTER) that cannot use bound parameters for identifiers.

    schema defaults to 'data' (single_tenant unchanged). In multi_tenant
    callers pass the per-tenant schema from tenant_data_schema(tid).
    The schema name is validated with the same SAFE_TABLE_NAME_RE — tenant
    schema names follow the same lowercase-alphanumeric-underscore pattern
    (``data_t_{uuid_underscored}``, matching ``tenant_data_schema()`` output).

    T-1209-05: both table_name AND schema are validated before interpolation.

    Re-exported from ``service.py`` for ``tests/test_sql_safety.py``.

    Raises
    ------
    ValueError
        If table_name or schema fails SAFE_TABLE_NAME_RE validation.
    """
    if not SAFE_TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")
    if not SAFE_TABLE_NAME_RE.match(schema):
        raise ValueError(f"Invalid schema name: {schema!r}")
    return f'"{schema}"."{table_name}"'
