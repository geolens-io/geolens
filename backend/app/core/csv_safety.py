"""One spreadsheet-formula escaping rule for every CSV this product writes.

fix(#1778): the rule was stated twice, in two private copies -- ``_safe_csv_cell``
in ``modules/audit/router.py`` and ``_safe`` in ``modules/admin/router.py`` --
and not at all in the third and most exposed writer. The dataset export
(``processing/export/ogr.py``) hands ogr2ogr the table and ogr2ogr writes every
attribute value verbatim; the writer side validates only the column NAME
(``_COLUMN_NAME_RE`` in features/service.py), never the value. So an editor on
any public dataset can store a property beginning with ``=``, ``+``, ``-`` or
``@`` and any anonymous visitor who downloads the CSV distribution the DCAT
record advertises executes it on open. That is a cross-privilege sink: the
writer needs edit rights on one dataset, the victim needs none. It is also the
one CSV in the product whose cells are wholly user-authored, while the two that
were hardened carry mostly system-generated fields.

The escape is a leading TAB, which spreadsheets treat as "this cell is text".

The default is strict: every cell starting with a trigger character is escaped,
which is exactly what the audit-log and admin-user exports have always done. A
username of ``+123`` or an account id of ``-001`` is a string that happens to
look like a number, and stripping its protection to keep a spreadsheet from
right-aligning it would be the wrong trade in a security log.

fix(#1778 codex r1, narrowed r2): ``allow_numeric`` exists for the dataset
export, and its callers must decide by COLUMN TYPE, never by the shape of the
value. In a column the database calls ``integer`` or ``double precision``,
``-12`` is a measurement: tab-prefixing it turns every negative reading in an
exported attribute table into text, for pandas and QGIS as much as for Excel,
and no spreadsheet reads a number as a formula anyway. In a text column ``-12``
is a string a user typed, indistinguishable from the first half of ``-12+A1``,
and it keeps the tab. ``numeric_column_names`` is the intended source of that
decision.
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
