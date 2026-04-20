"""Shared text-processing utilities used across Pydantic schemas."""

import unicodedata


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
