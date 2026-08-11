"""SQL identifier validation and quoting for the ingest metadata modules.

Split out of ``metadata.py`` (#1042). Table names reach these helpers from
source files and from tenant-schema derivation, and they are identifiers rather
than parameterizable values, so every one is validated against a strict pattern
before it is interpolated into a statement.

This module is the base of the ``metadata_*`` import graph: each of the other
modules needs these four, and nothing here needs anything from them. That is
what lets the extent, geometry, mercator, projection, quality and attribute
modules stay independent of one another instead of collapsing back into one
file through a shared helper.
"""

import re


_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _validate_table_name(table_name: str) -> None:
    """Validate table name matches safe identifier pattern."""
    if not _TABLE_NAME_RE.match(table_name):
        raise ValueError(
            f"Invalid table name: {table_name!r}. "
            "Must contain only lowercase letters, digits, and underscores."
        )


def _qtable(table_name: str, schema: str = "data") -> str:
    """Return quoted '<schema>.table_name' identifier after validation.

    In single_tenant, schema='data' (unchanged behavior).
    In multi_tenant, callers pass the per-tenant schema from
    ``tenant_data_schema(current_tenant_var.get())``.
    Both table_name and schema are validated against the same safe-identifier
    pattern (lowercase alphanumeric + underscore) before interpolation
    (T-1209-05: SQL-identifier injection guard).
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)  # schema names follow the same safe pattern
    return f'"{schema}"."{table_name}"'


def _sql_quote_ident(name: str) -> str:
    """Return a safely double-quoted SQL identifier for use inside text().

    Handles embedded double-quotes by doubling them, which is the
    PostgreSQL-standard escape. Centralizes the quoting logic that
    previously lived inline at every call site (PERF-6, KISS).

    fix(#640): colons are backslash-escaped because SQLAlchemy ``text()``
    parses ``:name`` as a bind parameter even inside double-quoted
    identifiers (Socrata exports ship columns literally named ``:id``,
    ``:created_at``, ...). ``text()`` unescapes ``\\:`` back to ``:`` at
    compile time, so the emitted SQL carries the literal identifier. The
    output is therefore only valid inside ``text()`` — do not pass it to
    ``exec_driver_sql`` or raw driver APIs.
    """
    return '"' + name.replace('"', '""').replace(":", "\\:") + '"'
