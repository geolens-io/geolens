"""STAC 1.0 serializer: transforms OGC Record dicts into STAC Item/Collection JSON.

Pure dict restructuring -- no database queries.
"""

from __future__ import annotations

from app.standards.ogc.utils import normalize_language_tag

# ---------------------------------------------------------------------------
# Conformance class URIs for the GeoLens STAC API
# ---------------------------------------------------------------------------

STAC_CONFORMANCE: list[str] = [
    "https://api.stacspec.org/v1.0.0/core",
    "https://api.stacspec.org/v1.0.0/collections",
    "https://api.stacspec.org/v1.0.0/item-search",
]

STAC_PROJECTION_EXTENSION_URI = (
    "https://stac-extensions.github.io/projection/v2.0.0/schema.json"
)
STAC_RASTER_EXTENSION_URI = (
    "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
)
STAC_LANGUAGE_EXTENSION_URI = (
    "https://stac-extensions.github.io/language/v1.0.0/schema.json"
)

# STAC extension properties that should be copied from OGC record properties
_STAC_EXTENSION_PROPS = (
    "proj:code",
    "proj:wkt2",
    "proj:shape",
    "gsd",
    "raster:bands",
)

_RTL_LANGS = {"ar", "fa", "he", "ur"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_stac_links(
    item_id: str,
    collection_id: str | None,
    stac_api_url: str,
) -> list[dict]:
    """Build the ``links`` array for a STAC Item."""
    self_href = (
        f"{stac_api_url}/collections/{collection_id}/items/{item_id}"
        if collection_id
        else f"{stac_api_url}/items/{item_id}"
    )
    links: list[dict] = [
        {
            "rel": "self",
            "href": self_href,
            "type": "application/geo+json",
        },
        {
            "rel": "root",
            "href": stac_api_url,
            "type": "application/json",
        },
        {
            "rel": "parent",
            "href": (
                f"{stac_api_url}/collections/{collection_id}"
                if collection_id
                else stac_api_url
            ),
            "type": "application/json",
        },
    ]
    if collection_id:
        links.append(
            {
                "rel": "collection",
                "href": f"{stac_api_url}/collections/{collection_id}",
                "type": "application/json",
            }
        )
    return links


def _build_language_object(language: object) -> dict | None:
    """Convert GeoLens' OGC language string into a STAC Language Object."""
    if not isinstance(language, str):
        return None

    code = normalize_language_tag(language)
    if code is None:
        return None

    result = {"code": code}
    base = code.split("-", 1)[0].lower()
    if base in _RTL_LANGS:
        result["dir"] = "rtl"
    return result


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _normalize_extension_uris(values: list[str]) -> list[str]:
    """Canonicalize extension versions whose properties GeoLens emits."""
    normalized: list[str] = []
    for value in values:
        if value.startswith("https://stac-extensions.github.io/projection/"):
            value = STAC_PROJECTION_EXTENSION_URI
        elif value.startswith("https://stac-extensions.github.io/raster/"):
            value = STAC_RASTER_EXTENSION_URI
        _append_unique(normalized, value)
    return normalized


def _projection_code(properties: dict) -> str | None:
    """Return a Projection Extension v2 code, accepting legacy input safely."""
    value = properties.get("proj:code")
    if value is None:
        value = properties.get("proj:epsg")
        if value is not None:
            value = f"EPSG:{value}"
    if value is None:
        return None
    return str(value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ogc_record_to_stac_item(
    record: dict,
    *,
    collection_id: str | None = None,
    stac_api_url: str,
) -> dict:
    """Transform an OGC Record Feature dict into a STAC 1.0 Item dict.

    Parameters
    ----------
    record:
        Dict produced by ``dataset_to_ogc_record()``.
    collection_id:
        Optional STAC collection this item belongs to.
    stac_api_url:
        Base URL for the STAC API (e.g. ``https://host/api/stac``).
    """
    props = record["properties"]

    # -- Core properties (datetime is ALWAYS present, may be null) ----------
    stac_props: dict = {
        "datetime": props.get("datetime"),
    }

    # Temporal range
    if props.get("start_datetime"):
        stac_props["start_datetime"] = props["start_datetime"]
        stac_props["end_datetime"] = props.get("end_datetime")

    # Descriptive
    if props.get("title"):
        stac_props["title"] = props["title"]
    if props.get("description"):
        stac_props["description"] = props["description"]

    stac_extensions = _normalize_extension_uris(
        list(record.get("stac_extensions") or [])
    )

    # Language (from OGC Record properties, serialized per the STAC language extension)
    language = _build_language_object(props.get("language"))
    if language:
        stac_props["language"] = language
        _append_unique(stac_extensions, STAC_LANGUAGE_EXTENSION_URI)

    # STAC extension properties. Projection v2 replaced integer ``proj:epsg``
    # with an authority-qualified string ``proj:code``. Accepting the legacy
    # key at this boundary keeps callers safe without ever emitting it.
    proj_code = _projection_code(props)
    if proj_code is not None:
        stac_props["proj:code"] = proj_code

    for key in _STAC_EXTENSION_PROPS:
        if key != "proj:code" and key in props:
            stac_props[key] = props[key]

    if any(key.startswith("proj:") for key in stac_props):
        _append_unique(stac_extensions, STAC_PROJECTION_EXTENSION_URI)
    if "raster:bands" in stac_props:
        _append_unique(stac_extensions, STAC_RASTER_EXTENSION_URI)

    # -- Build Item ---------------------------------------------------------
    item: dict = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": record["id"],
        "geometry": record.get("geometry"),
        "properties": stac_props,
        "links": _build_stac_links(record["id"], collection_id, stac_api_url),
        "assets": record.get("assets", {}),
    }
    if record.get("bbox") is not None:
        item["bbox"] = record["bbox"]

    # STAC extensions
    if stac_extensions:
        item["stac_extensions"] = stac_extensions

    # Collection membership
    if collection_id:
        item["collection"] = collection_id

    return item


def ogc_collection_to_stac_collection(
    collection_id: str,
    name: str,
    description: str | None,
    *,
    spatial_extent: list[float] | None = None,
    temporal_extent: list[str | None] | None = None,
    stac_api_url: str,
    keywords: list[str] | None = None,
    summaries: dict | None = None,
) -> dict:
    """Build a STAC Collection dict from GeoLens collection metadata.

    Parameters
    ----------
    collection_id:
        Unique identifier for the collection.
    name:
        Human-readable collection title.
    description:
        Collection description (falls back to empty string).
    spatial_extent:
        ``[west, south, east, north]`` bounding box. Defaults to global.
    temporal_extent:
        ``[start, end]`` ISO-8601 strings (either can be ``None``).
    stac_api_url:
        Base URL for the STAC API.
    """
    result: dict = {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": collection_id,
        "title": name,
        "description": description or "",
        "license": "proprietary",
        "extent": {
            "spatial": {
                "bbox": [spatial_extent or [-180, -90, 180, 90]],
            },
            "temporal": {
                "interval": [temporal_extent or [None, None]],
            },
        },
        "links": [
            {
                "rel": "self",
                "href": f"{stac_api_url}/collections/{collection_id}",
                "type": "application/json",
            },
            {
                "rel": "root",
                "href": stac_api_url,
                "type": "application/json",
            },
            {
                "rel": "parent",
                "href": stac_api_url,
                "type": "application/json",
            },
            {
                "rel": "items",
                "href": f"{stac_api_url}/collections/{collection_id}/items",
                "type": "application/geo+json",
            },
        ],
    }
    if keywords:
        result["keywords"] = keywords
    if summaries:
        result["summaries"] = summaries
        if any(key.startswith("proj:") for key in summaries):
            result["stac_extensions"] = [STAC_PROJECTION_EXTENSION_URI]
    return result
