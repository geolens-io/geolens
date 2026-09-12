"""Spreadsheet-formula escaping shared by every CSV export.

Formula-triggering cells receive a leading tab so spreadsheets read them as
text. Escaping is strict by default, including strings that look numeric such
as account ID ``-001``. Dataset exports may set ``allow_numeric`` according to
the declared column type; a value's shape alone cannot distinguish a numeric
measurement from a formula fragment in a text column.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

#: The characters a spreadsheet may read as the start of a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@")

# Anchored, and deliberately narrow: an optional sign, digits with at most one
# decimal point, an optional exponent. No thousands separators, no currency, no
# leading or trailing space -- anything the regex is unsure about is escaped.
# It gates the value even inside a numeric column, so a NULL rendered as an
# empty string or a driver-specific sentinel cannot slip through unescaped.
_PLAIN_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")

# information_schema.columns.data_type values PostgreSQL reports for the numeric
# types, which is what `get_column_info` stores in a dataset's column_info.
NUMERIC_SQL_TYPES: frozenset[str] = frozenset(
    {
        "smallint",
        "integer",
        "bigint",
        "decimal",
        "numeric",
        "real",
        "double precision",
    }
)


def escape_csv_formula(value: str, *, allow_numeric: bool = False) -> str:
    """Prefix a formula-triggering cell with a tab so it is read as text.

    ``allow_numeric`` leaves well-formed decimal numbers alone. Pass it only
    for a column whose declared type is numeric.
    """
    if not value or value[0] not in FORMULA_PREFIXES:
        return value
    if allow_numeric and _PLAIN_NUMBER_RE.match(value):
        return value
    return "\t" + value


def numeric_column_names(column_info: Iterable[Mapping] | None) -> frozenset[str]:
    """Names of the columns a dataset's ``column_info`` declares numeric.

    The one sanctioned input to ``allow_numeric``. ``column_info`` rows come
    from ``get_column_info``, which stores ``information_schema.columns``'
    ``data_type`` verbatim.
    """
    if not column_info:
        return frozenset()
    return frozenset(
        name
        for row in column_info
        if isinstance(row, Mapping)
        and isinstance(name := row.get("name"), str)
        and isinstance(dtype := row.get("type"), str)
        and dtype.lower() in NUMERIC_SQL_TYPES
    )
