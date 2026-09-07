"""STAC API adapter: connect, list collections, and search items over httpx.

The user-supplied STAC API URL is SSRF-validated upstream by the router;
timeouts are enforced via STAC_TIMEOUT / DEFAULT_CHECK_TIMEOUT.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, TypedDict
from urllib.parse import urljoin

import httpx
import structlog
from pydantic import HttpUrl

from app.core.url_redaction import has_url_credentials, redact_exception_text
from app.platform.security import make_safe_client
from app.platform.probe_bounds import bounded_probe_read
from app.platform.service_endpoints import (
    DEFAULT_CHECK_TIMEOUT,
    OGC_JSON_ACCEPT,
    EndpointCheckFailedError,
)

logger = structlog.stdlib.get_logger(__name__)

# Maximum items to return per search request
MAX_SEARCH_ITEMS = 100
# Connection timeout for STAC API requests
STAC_TIMEOUT = 30.0


def projection_epsg(properties: dict[str, Any]) -> int | None:
    """Return an EPSG identifier from Projection Extension v2 or legacy data."""
    projection_code = properties.get("proj:code")
    if isinstance(projection_code, str) and projection_code.startswith("EPSG:"):
        code = projection_code.removeprefix("EPSG:")
        if code.isdecimal():
            return int(code)

    legacy_epsg = properties.get("proj:epsg")
    if isinstance(legacy_epsg, int) and not isinstance(legacy_epsg, bool):
        return legacy_epsg
    return None


# STAC sets no length limit on an asset key, so this is GeoLens's own bound
# on the string that ends up in `origin_ref`; applied at capture (here) as
# well as at the import model, since a key too long for the model would
# 422 the caller's whole search batch. An over-long key just imports
# without one, and refresh falls back to matching on the href.
MAX_ASSET_KEY_CHARS = 255

# feat(#1692): width of DatasetAsset.media_type (String(100)); same
# capture-side bound and reason as MAX_ASSET_KEY_CHARS above.
MAX_ASSET_MEDIA_TYPE_CHARS = 100


def storable_media_type(media_type: str | None) -> str | None:
    """The asset's declared media type if it fits the column, else None.

    feat(#1692): applied here and again on refresh, so every writer of
    ``DatasetAsset.media_type`` carries the column's bound.
    """
    if not isinstance(media_type, str) or len(media_type) > MAX_ASSET_MEDIA_TYPE_CHARS:
        return None
    return media_type


def storable_asset_key(key: str | None) -> str | None:
    """The asset key if it is short enough to carry, else None.

    fix(#1331): ``""`` is a legal STAC asset key and is deliberately NOT
    refused here — downstream (``stac_resolve.py``) tests a stored key with
    ``is not None``, never truthiness, so ``""`` still means "recorded" and
    a resolve can round-trip a moved asset without losing the key.
    """
    if key is None or len(key) > MAX_ASSET_KEY_CHARS:
        return None
    return key


# Keys a published COG hides behind, in try order: `data`/`visual` are the
# STAC-common spellings, `image` the older one, `B04` Sentinel-2's red band.
_PREFERRED_ASSET_KEYS: tuple[str, ...] = ("data", "visual", "image", "B04")


def pick_data_asset(assets: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The item's primary data asset, as ``(key, asset)``, or None.

    feat(#1266): shared by search and by refresh re-picking from the same
    item fetched again later, so both agree instead of drifting to a
    different band. The key is returned alongside the asset because it is
    the durable name that survives an href moving.

    Non-dict entries are skipped: a malformed catalog with a scalar asset
    value must not raise inside search.
    """
    if not isinstance(assets, dict):
        return None
    for key in _PREFERRED_ASSET_KEYS:
        asset = assets.get(key)
        if isinstance(asset, dict) and asset:
            return key, asset
    for key, asset in assets.items():
        if isinstance(asset, dict) and "data" in (asset.get("roles") or []):
            return key, asset
    return None


def storable_href(href: Any, base_url: str) -> str | None:
    """Resolve *href* against *base_url*, or None if it may not be STORED.

    feat(#1266): shared by ``self_link_href`` for the item href and here for
    the asset href — both end up in ``origin_ref`` and must clear the same
    bar as the import request model: pydantic ``HttpUrl``, the model's 4096
    cap, and the ADR-002 invariant-4 credential refusal (a signed URL must
    never reach the source binding).

    A relative href is legal STAC, so it is resolved BEFORE any check —
    otherwise ``//user:pw@host/x`` could smuggle userinfo past a raw scan.
    """
    if not isinstance(href, str) or not href.strip():
        return None
    try:
        resolved = urljoin(base_url, href)
        HttpUrl(resolved)
    except ValueError:
        return None
    if len(resolved) > 4096 or has_url_credentials(resolved):
        return None
    return resolved


def self_link_href(feature: dict[str, Any], base_url: str) -> str | None:
    """The item's own canonical href, from its ``rel="self"`` link.

    feat(#1222): search is the ONE place GeoLens holds a STAC item document,
    so it is the only place the item's own href can be captured — without
    it, ``origin_ref``'s ``item_href`` stays unwritten and the health probe
    can only ever check the asset, never a withdrawal from the catalog.

    A relative href is legal STAC, so it is resolved against the response's
    actual URL before any check (fix(#1271) review). ``storable_href`` then
    drops a non-http(s) or credentialed href rather than surfacing it: a
    credentialed one would otherwise turn an optional convenience into a
    422 for the caller's whole import batch.
    """
    links = feature.get("links")
    # fix(#1271): a malformed scalar `links` must cost only this
    # optional field, not 502 the whole search.
    for link in links if isinstance(links, list) else []:
        if not isinstance(link, dict) or link.get("rel") != "self":
            continue
        resolved = storable_href(link.get("href"), base_url)
        if resolved is not None:
            return resolved
    return None


def _make_client() -> httpx.AsyncClient:
    """Shared httpx client for STAC API requests.

    Phase 1061 SEC-S04: uses make_safe_client() so the per-hop SSRF
    revalidation hook covers every redirect a STAC probe follows.
    """
    return make_safe_client(timeout=STAC_TIMEOUT)


async def connect_stac_api(url: str) -> dict | None:
    """Validate a STAC API URL and return landing page info, or None.

    fix(#1770): the whole function runs under ``DEFAULT_CHECK_TIMEOUT``,
    same reasoning as ``probe_ogcapi``.
    """
    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            return await _connect_stac_api_within_deadline(url)
    except TimeoutError:
        logger.debug("STAC connect: deadline exceeded", url=url)
        return None


async def _connect_stac_api_within_deadline(url: str) -> dict | None:
    async with _make_client() as client:
        headers = {"Accept": "application/json"}
        try:
            # fix(#1770): bounded read, not a plain `client.get` — see
            # `bounded_probe_read`'s docstring.
            body, _ = await bounded_probe_read(
                client, url, headers=headers, accept=OGC_JSON_ACCEPT
            )
        except (
            httpx.HTTPStatusError,
            httpx.TransportError,
            EndpointCheckFailedError,
        ) as exc:
            logger.debug(
                "STAC connect failed", url=url, error=redact_exception_text(exc)
            )
            return None

        try:
            data = json.loads(body)
        except (
            Exception
        ):  # broad: json.loads can throw varied decoder errors; treat as non-STAC
            logger.debug("STAC connect: non-JSON response", url=url)
            return None

        # fix(#1770): a `200 []`/`200 null`/`200 "x"` response is valid JSON
        # but not a dict, and `.get(...)` on it raises `AttributeError`
        # instead of degrading to "not a STAC API" below.
        if not isinstance(data, dict):
            logger.debug("STAC connect: non-dict response", url=url)
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

        # Find the primary data asset (COG), through the same choice the
        # refresh strategy re-makes later (feat #1266).
        picked = pick_data_asset(assets)
        data_asset_key, data_asset = picked if picked else (None, None)

        # Find thumbnail
        thumbnail = assets.get("thumbnail") or next(
            (a for a in assets.values() if "thumbnail" in (a.get("roles") or [])),
            None,
        )

        # Extract datetime — may be null with start/end range
        dt = props.get("datetime")
        dt_start = props.get("start_datetime") or dt
        dt_end = props.get("end_datetime") or dt

        # EW-05: surface file:size so the frontend can show an estimated
        # download size before the user commits to a multi-GB fetch.
        data_asset_size_bytes = data_asset.get("file:size") if data_asset else None
        if not isinstance(data_asset_size_bytes, int):
            data_asset_size_bytes = None  # be defensive — bad-shape values become None

        items.append(
            {
                "id": f.get("id"),
                "collection": f.get("collection"),
                # resp.url is the LOGICAL post-redirect URL — the SSRF
                # transport restores the hostname after each pinned hop
                # (_SSRFGuardTransport) — so a relative self link resolves
                # against the caller's host, never the pinned IP.
                "item_href": self_link_href(f, str(resp.url)),
                "bbox": f.get("bbox"),
                "datetime": dt,
                "datetime_start": dt_start,
                "datetime_end": dt_end,
                "title": props.get("title", f.get("id")),
                "epsg": projection_epsg(props),
                "gsd": props.get("gsd"),
                "cloud_cover": props.get("eo:cloud_cover"),
                "data_asset_href": data_asset.get("href") if data_asset else None,
                # feat(#1692): bounded to fit DatasetAsset.media_type.
                "data_asset_type": storable_media_type(
                    data_asset.get("type") if data_asset else None
                ),
                # feat(#1266): durable name that survives the href moving,
                # so refresh can follow the move instead of re-picking.
                "data_asset_key": storable_asset_key(data_asset_key),
                "data_asset_size_bytes": data_asset_size_bytes,
                "thumbnail_href": thumbnail.get("href") if thumbnail else None,
                "asset_count": len(assets),
            }
        )

    return {
        "items": items,
        "matched": matched,
        "returned": len(items),
    }
