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

A cell that parses as a plain decimal number is exempt, and that exemption is
what makes the rule safe to apply to a data export rather than only to an audit
log. ``-12`` is not a formula in any spreadsheet -- Excel, LibreOffice and
Sheets all read it as the number -12, and a leading ``+`` is simply dropped --
so tab-prefixing it would convert every negative measurement in an exported
attribute table into text, for the spreadsheet AND for pandas, QGIS and every
other reader. Anything that is NOT a well-formed number keeps the escape:
``-12+A1`` and ``+1-cmd|'/c calc'!A0`` are not numbers, and neither is a bare
``-``.
"""

from __future__ import annotations

import re

#: The characters a spreadsheet may read as the start of a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@")

# Anchored, and deliberately narrow: an optional sign, digits with at most one
# decimal point, an optional exponent. No thousands separators, no currency, no
# leading or trailing space -- anything the regex is unsure about is escaped.
_PLAIN_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


def escape_csv_formula(value: str) -> str:
    """Prefix a formula-triggering cell with a tab so it is read as text."""
    if not value or value[0] not in FORMULA_PREFIXES:
        return value
    if _PLAIN_NUMBER_RE.match(value):
        return value
    return "\t" + value
