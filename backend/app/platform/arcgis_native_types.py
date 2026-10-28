"""PostgreSQL types GeoLens gives the ArcGIS fields GDAL's ESRIJSON driver loads as text."""

from app.platform.column_names import stored_column_names

# TimeOnly stays text: the feature APIs and OGC queryables have no time type.
ARCGIS_NATIVE_PG_TYPES: dict[str, str] = {
    "esriFieldTypeBigInteger": "bigint",
    "esriFieldTypeDateOnly": "date",
    "esriFieldTypeTimestampOffset": "timestamp with time zone",
}


def column_casts_from_meta(meta: dict) -> dict[str, str]:
    """Esri type by stored column name, for the fields that get a native type."""
    raw_fields = meta.get("fields") if isinstance(meta, dict) else None
    if not isinstance(raw_fields, list):
        return {}
    fields = [
        f
        for f in raw_fields
        if isinstance(f, dict)
        and isinstance(f.get("name"), str)
        and f.get("type") != "esriFieldTypeGeometry"
    ]
    stored = stored_column_names([f["name"] for f in fields])
    return {
        column.encode()[:63].decode(errors="ignore"): f["type"]
        for f, column in zip(fields, stored, strict=True)
        if isinstance(f.get("type"), str) and f["type"] in ARCGIS_NATIVE_PG_TYPES
    }
