"""SQL identifier validation and quoting for the ingest metadata modules.

Table/schema names are identifiers, not parameterizable values, so every one
is validated against a strict pattern before interpolation into a statement.
Base of the ``metadata_*`` import graph — nothing here depends on them.
"""

import re


_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _validate_table_name(table_name: str) -> None:
    if not _TABLE_NAME_RE.match(table_name):
        raise ValueError(
            f"Invalid table name: {table_name!r}. "
            "Must contain only lowercase letters, digits, and underscores."
        )


def _qtable(table_name: str, schema: str = "data") -> str:
    """Return the quoted ``"schema"."table_name"`` after validating both.

    multi_tenant callers pass the per-tenant schema from
    ``tenant_data_schema(current_tenant_var.get())``.
    """
    _validate_table_name(table_name)
    _validate_table_name(schema)
    return f'"{schema}"."{table_name}"'


def _sql_quote_ident(name: str) -> str:
    """Return a double-quoted SQL identifier for use inside ``text()`` only.

    Colons are backslash-escaped because ``text()`` parses ``:name`` as a bind
    parameter even inside quoted identifiers, and unescapes ``\\:`` at compile
    time; ``exec_driver_sql`` and raw driver APIs would keep the backslash.
    """
    return '"' + name.replace('"', '""').replace(":", "\\:") + '"'
