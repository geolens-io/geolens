"""Field aliases and descriptions a remote service publishes for its attributes."""

from app.platform.column_names import stored_column_names

_PG_IDENTIFIER_BYTES = 63
_MAX_ALIAS = 500
_MAX_DESCRIPTION = 2000


def _clean(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    # JSONB and Text reject NUL and unpaired surrogates, both legal in JSON.
    text = value.replace("\x00", "").encode("utf-8", "ignore").decode().strip()
    return text[:limit] if text else None


def _pg_truncated(column: str) -> str:
    """The identifier PostgreSQL keeps when a stored name exceeds its byte limit."""
    return column.encode()[:_PG_IDENTIFIER_BYTES].decode(errors="ignore")


def arcgis_field_labels(meta: dict) -> dict[str, dict[str, str]]:
    """Per stored column name, the alias and description that add information.

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
    labels: dict[str, dict[str, str]] = {}
    for field, column in zip(fields, stored, strict=True):
        name = field["name"]
        label: dict[str, str] = {}
        alias = _clean(field.get("alias"), _MAX_ALIAS)
        if alias is not None and alias != name:
            label["alias"] = alias
        description = _clean(field.get("description"), _MAX_DESCRIPTION)
        if description is not None:
            label["description"] = description
        if label:
            labels[_pg_truncated(column)] = label
    return labels
