"""STAC 1.0 serializer: transforms OGC Record dicts into STAC Item/Collection JSON.

Pure dict restructuring -- no database queries.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Conformance class URIs for the GeoLens STAC API
# ---------------------------------------------------------------------------

STAC_CONFORMANCE: list[str] = [
    "https://api.stacspec.org/v1.0.0/core",
    "https://api.stacspec.org/v1.0.0/collections",
    "https://api.stacspec.org/v1.0.0/item-search",
    "https://api.stacspec.org/v1.0.0/ogcapi-features",
]

# STAC extension properties that should be copied from OGC record properties
_STAC_EXTENSION_PROPS = ("proj:epsg", "proj:shape", "gsd", "bands")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_stac_links(
    item_id: str,
    collection_id: str | None,
    stac_api_url: str,
) -> list[dict]:
    """Build the ``links`` array for a STAC Item."""
    links: list[dict] = [
        {
            "rel": "self",
            "href": f"{stac_api_url}/items/{item_id}",
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

    # STAC extension properties
    for key in _STAC_EXTENSION_PROPS:
        if key in props:
            stac_props[key] = props[key]

    # -- Build Item ---------------------------------------------------------
    item: dict = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": record["id"],
        "geometry": record.get("geometry"),
        "bbox": record.get("bbox"),
        "properties": stac_props,
        "links": _build_stac_links(record["id"], collection_id, stac_api_url),
        "assets": record.get("assets", {}),
    }

    # STAC extensions
    if record.get("stac_extensions"):
        item["stac_extensions"] = record["stac_extensions"]

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
    return result
