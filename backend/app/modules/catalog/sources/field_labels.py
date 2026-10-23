"""Field aliases and descriptions a remote service publishes for its attributes."""

from typing import Any

from app.platform.column_names import stored_column_names

_PG_IDENTIFIER_BYTES = 63
_MAX_ALIAS = 500
_MAX_DESCRIPTION = 2000
MAX_VALUE_LABELS = 5000
MAX_VALUE_LABEL_LENGTH = 500


def _clean(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    # JSONB and Text reject NUL and unpaired surrogates, both legal in JSON.
    text = value.replace("\x00", "").encode("utf-8", "ignore").decode().strip()
    return text[:limit] if text else None


def _code_text(code: object) -> str | None:
    if isinstance(code, bool):
        return None
    if isinstance(code, float) and code.is_integer():
        code = int(code)
    if isinstance(code, int):
        return str(code)
    # A code must match its feature value exactly, so one the store cannot keep
    # as given is skipped, not rewritten.
    if not isinstance(code, str) or len(code) > MAX_VALUE_LABEL_LENGTH:
        return None
    try:
        code.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return None if "\x00" in code else code


def _coded_value_labels(domain: object) -> dict[str, str] | None:
    """Label per code of a ``codedValue`` domain, keyed by the code as text."""
    if not isinstance(domain, dict) or domain.get("type") != "codedValue":
        return None
    labels: dict[str, str] = {}
    for entry in domain.get("codedValues") or []:
        if not isinstance(entry, dict):
            continue
        code = _code_text(entry.get("code"))
        name = _clean(entry.get("name"), MAX_VALUE_LABEL_LENGTH)
        if code is None or name is None or code in labels:
            continue
        labels[code] = name
        if len(labels) == MAX_VALUE_LABELS:
            break
    return labels or None


def _pg_truncated(column: str) -> str:
    """The identifier PostgreSQL keeps when a stored name exceeds its byte limit."""
    return column.encode()[:_PG_IDENTIFIER_BYTES].decode(errors="ignore")


def arcgis_field_labels(meta: dict) -> dict[str, dict[str, Any]]:
    """Per stored column name, the alias, description and code labels it publishes.

    Names are resolved over the whole field list, because a rename that
    collides with another column depends on the columns around it. An alias
    equal to the field name says nothing, so it is left out and the humanized
    title stays.
    """
    fields = [
        field
        for field in meta.get("fields") or []
        if isinstance(field, dict)
        and isinstance(field.get("name"), str)
        and field.get("type") != "esriFieldTypeGeometry"
    ]
    stored = stored_column_names([field["name"] for field in fields])
    labels: dict[str, dict[str, Any]] = {}
    for field, column in zip(fields, stored, strict=True):
        name = field["name"]
        label: dict[str, Any] = {}
        alias = _clean(field.get("alias"), _MAX_ALIAS)
        if alias is not None and alias != name:
            label["alias"] = alias
        description = _clean(field.get("description"), _MAX_DESCRIPTION)
        if description is not None:
            label["description"] = description
        value_labels = _coded_value_labels(field.get("domain"))
        if value_labels is not None:
            label["value_labels"] = value_labels
        if label:
            labels[_pg_truncated(column)] = label
    return labels
