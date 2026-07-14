"""Shared text-processing and query-string utilities.

This module deliberately has no product-domain dependencies, so helpers used by
catalog, administration, audit, and sharing code have one stable home.
"""

import unicodedata

__all__ = ["escape_ilike", "normalize_nfc"]


def escape_ilike(value: str) -> str:
    """Escape a value for a SQL ``LIKE``/``ILIKE`` pattern.

    Backslash must be escaped before ``%`` and ``_``.  Callers still need to
    pass ``escape="\\"`` to SQLAlchemy and add their own wildcard anchors::

        pattern = f"%{escape_ilike(search)}%"
        column.ilike(pattern, escape="\\")
    """
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def normalize_nfc(v: str | None) -> str | None:
    """Normalize a string to Unicode NFC form.

    Use as a Pydantic ``field_validator`` on user-facing text fields to
    prevent invisible duplicates caused by different byte representations
    of the same visual characters (e.g. ``e`` + combining accent vs.
    precomposed ``é``).
    """
    if v is None:
        return v
    return unicodedata.normalize("NFC", v)
