"""Field aliases and descriptions a remote service publishes for its attributes."""

_MAX_ALIAS = 500
_MAX_DESCRIPTION = 2000


def _clean(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:limit] if text else None


def arcgis_field_labels(meta: dict) -> dict[str, dict[str, str]]:
    """Per source field name, the alias and description that add information.

    An alias equal to the field name says nothing, so it is left out and the
    humanized title stays.
    """
    labels: dict[str, dict[str, str]] = {}
    for field in meta.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        if not isinstance(name, str) or field.get("type") == "esriFieldTypeGeometry":
            continue
        label: dict[str, str] = {}
        alias = _clean(field.get("alias"), _MAX_ALIAS)
        if alias is not None and alias != name:
            label["alias"] = alias
        description = _clean(field.get("description"), _MAX_DESCRIPTION)
        if description is not None:
            label["description"] = description
        if label:
            labels[name] = label
    return labels
