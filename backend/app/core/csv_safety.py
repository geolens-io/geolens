"""One spreadsheet-formula escaping rule for every CSV this product writes.

fix(#1778): previously duplicated across two private copies and missing
entirely from the dataset export, whose column-name validation never checked
cell values — letting an editor on any public dataset store a property
starting with ``=``, ``+``, ``-`` or ``@`` that executes when a visitor opens
the downloaded CSV. The escape is a leading TAB, which spreadsheets read as
"this cell is text".

Strict by default: every cell starting with a trigger character is escaped,
even a string that only looks numeric (e.g. account id ``-001``) — the right
trade for the audit-log and admin-user exports.

fix(#1778): ``allow_numeric`` exists only for the
dataset export and must be decided by COLUMN TYPE, never by the value's
shape — ``-12`` is a measurement in a numeric column but an indistinguishable
formula fragment in a text column. ``numeric_column_names`` is the intended
source of that decision.
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

    ``allow_numeric`` leaves a cell alone when it is a well-formed decimal
    number. Pass it only for a column whose declared type is numeric; see the
    module docstring for why the value's shape is not enough on its own.
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
