"""Shared text-processing and query-string utilities.

This module deliberately has no product-domain dependencies, so helpers used by
catalog, administration, audit, and sharing code have one stable home.
"""

import unicodedata

__all__ = ["escape_ilike", "normalize_nfc", "reject_html_markup"]


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


def reject_html_markup(v: str | None) -> str | None:
    """Reject angle brackets in free text that lands in an HTML render context.

    fix(#1472): dataset ``attribution`` reaches MapLibre's attribution
    control, which assigns it to ``innerHTML``. MapLibre's own sanitizer only
    strips ``<script>``/``on*``/``javascript:``/``data:``, so ``<img src>``,
    ``<iframe src>`` and inline ``style`` survive it — letting an editor-
    supplied credit line beacon a viewer's IP or overlay any public map
    showing that dataset.

    A credit line is prose, so this rejects the two characters that open a tag
    rather than allowlisting elements — real org names (ampersands,
    apostrophes, accents) are untouched. Use as a Pydantic ``field_validator``
    on write paths; render boundaries also escape, so a bypassing value stays
    inert.
    """
    if v is not None and ("<" in v or ">" in v):
        raise ValueError(
            "must not contain '<' or '>' — this text is displayed as a credit "
            "line, not as markup"
        )
    return v
