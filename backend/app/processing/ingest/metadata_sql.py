"""SQL identifier validation and quoting for the ingest metadata modules.

Table/schema names are identifiers, not parameterizable values, so every one
is validated against a strict pattern before interpolation into a statement.
Base of the ``metadata_*`` import graph — nothing here depends on them.
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

    schema defaults to 'data' (single_tenant); multi_tenant callers pass the
    per-tenant schema from ``tenant_data_schema(current_tenant_var.get())``.
    Both are validated against the safe-identifier pattern before
    interpolation (SQL-identifier injection guard).
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)  # schema names follow the same safe pattern
    return f'"{schema}"."{table_name}"'


def _sql_quote_ident(name: str) -> str:
    """Return a safely double-quoted SQL identifier for use inside text().

    Doubles embedded double-quotes (PostgreSQL-standard escape).

    fix(#640): colons are backslash-escaped because SQLAlchemy ``text()``
    parses ``:name`` as a bind parameter even inside quoted identifiers
    (e.g. a column literally named ``:id``); ``text()`` unescapes ``\\:``
    back to ``:`` at compile time. Valid only inside ``text()`` — do not
    pass this to ``exec_driver_sql`` or raw driver APIs.
    """
    return '"' + name.replace('"', '""').replace(":", "\\:") + '"'
