"""STAC API adapter for connecting to remote SpatioTemporal Asset Catalogs.

Provides functions to connect, list collections, and search items from
external STAC APIs using httpx for HTTP interaction.

# Safety notes
# ------------
# The user-supplied STAC API URL is SSRF-validated upstream by the router.
# Timeouts are enforced via httpx client settings (STAC_TIMEOUT).
"""

from __future__ import annotations

from typing import Any, TypedDict

import httpx
import structlog

logger = structlog.stdlib.get_logger(__name__)

# Maximum items to return per search request
MAX_SEARCH_ITEMS = 100
# Connection timeout for STAC API requests
STAC_TIMEOUT = 30.0


def _make_client() -> httpx.AsyncClient:
    """Shared httpx client configuration for STAC API requests."""
    return httpx.AsyncClient(
        timeout=STAC_TIMEOUT,
        follow_redirects=True,
        max_redirects=5,
    )


async def connect_stac_api(url: str) -> dict | None:
    """Validate a STAC API URL and return landing page info.

    Returns a dict with id, title, description, stac_version, conformsTo,
    or None if the URL is not a valid STAC API.
    """
    async with _make_client() as client:
        headers = {"Accept": "application/json"}
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            logger.debug("STAC connect failed", url=url, error=str(exc))
            return None

        try:
            data = resp.json()
        except Exception:  # broad: httpx response.json() can throw varied parser/decoder errors; treat as non-STAC
            logger.debug("STAC connect: non-JSON response", url=url)
            return None

        # Must have stac_version or type == "Catalog"
        if not data.get("stac_version") and data.get("type") not in ("Catalog", "API"):
            logger.debug("STAC connect: not a STAC API", url=url)
            return None

        return {
            "id": data.get("id", "unknown"),
            "title": data.get("title", data.get("id", "STAC Catalog")),
            "description": data.get("description", ""),
            "stac_version": data.get("stac_version", "unknown"),
            "conforms_to": data.get("conformsTo", []),
        }


class StacCollectionDict(TypedDict):
    """Shape of a single collection entry returned by ``list_stac_collections``."""

    id: str
    title: str
    description: str
    license: str | None
    keywords: list[str]
    bbox: list[float] | None
    temporal_start: str | None
    temporal_end: str | None
    item_count: int | None


async def list_stac_collections(url: str) -> list[StacCollectionDict]:
    """Fetch collections from a STAC API.

    Returns a list of collection dicts with id, title, description,
    spatial_extent, temporal_extent, and item_count (if available).
    """
    collections_url = url.rstrip("/") + "/collections"

    async with _make_client() as client:
        headers = {"Accept": "application/json"}
        resp = await client.get(collections_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    raw_collections = data.get("collections", [])
    result = []
    for c in raw_collections:
        extent = c.get("extent", {})
        spatial = extent.get("spatial", {})
        temporal = extent.get("temporal", {})

        bbox = spatial.get("bbox", [[]])[0] if spatial.get("bbox") else None
        time_interval = (
            temporal.get("interval", [[]])[0] if temporal.get("interval") else None
        )

        # Some STAC APIs include item count in collection metadata
        item_count = c.get("numberMatched") or c.get("numberReturned")

        result.append(
            {
                "id": c["id"],
                "title": c.get("title", c["id"]),
                "description": c.get("description", ""),
                "license": c.get("license"),
                "keywords": c.get("keywords", []),
                "bbox": bbox,
                "temporal_start": time_interval[0]
                if time_interval and len(time_interval) > 0
                else None,
                "temporal_end": time_interval[1]
                if time_interval and len(time_interval) > 1
                else None,
                "item_count": item_count,
            }
        )

    return result


async def search_stac_items(
    url: str,
    *,
    collections: list[str] | None = None,
    bbox: list[float] | None = None,
    datetime_range: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search for items in a STAC API.

    Returns a dict with items list and matched count.
    """
    search_url = url.rstrip("/") + "/search"
    limit = min(limit, MAX_SEARCH_ITEMS)

    body: dict[str, Any] = {"limit": limit}
    if collections:
        body["collections"] = collections
    if bbox:
        body["bbox"] = bbox
    if datetime_range:
        body["datetime"] = datetime_range

    async with _make_client() as client:
        headers = {
            "Accept": "application/geo+json, application/json",
            "Content-Type": "application/json",
        }
        resp = await client.post(search_url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", [])
    matched = data.get("numberMatched") or data.get("context", {}).get("matched")

    items = []
    for f in features:
        props = f.get("properties", {})
        assets = f.get("assets", {})

        # Find the primary data asset (COG)
        data_asset = (
            assets.get("data")
            or assets.get("visual")
            or assets.get("image")
            or assets.get("B04")  # Sentinel-2 common band
            or next(
                (a for a in assets.values() if "data" in (a.get("roles") or [])),
                None,
            )
        )

        # Find thumbnail
        thumbnail = assets.get("thumbnail") or next(
            (a for a in assets.values() if "thumbnail" in (a.get("roles") or [])),
            None,
        )

        # Extract datetime — may be null with start/end range
        dt = props.get("datetime")
        dt_start = props.get("start_datetime") or dt
        dt_end = props.get("end_datetime") or dt

        items.append(
            {
                "id": f.get("id"),
                "collection": f.get("collection"),
                "bbox": f.get("bbox"),
                "datetime": dt,
                "datetime_start": dt_start,
                "datetime_end": dt_end,
                "title": props.get("title", f.get("id")),
                "epsg": props.get("proj:epsg"),
                "gsd": props.get("gsd"),
                "cloud_cover": props.get("eo:cloud_cover"),
                "data_asset_href": data_asset.get("href") if data_asset else None,
                "data_asset_type": data_asset.get("type") if data_asset else None,
                "thumbnail_href": thumbnail.get("href") if thumbnail else None,
                "asset_count": len(assets),
            }
        )

    return {
        "items": items,
        "matched": matched,
        "returned": len(items),
    }
