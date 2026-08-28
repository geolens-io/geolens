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
from urllib.parse import urljoin

import httpx
import structlog
from pydantic import HttpUrl

from app.core.url_redaction import has_url_credentials
from app.platform.security import make_safe_client

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


# The longest asset key GeoLens will carry. STAC puts no limit on an asset
# identifier, so this is GeoLens's own bound on a third-party string that
# ends up in `origin_ref` — and because it is a bound rather than a fact
# about STAC, it has to be applied at CAPTURE as well as at the import
# model. Search surfacing a key the import model would reject is how one
# unusual item turns into a 422 for the caller's whole batch, which is the
# same trap `self_link_href` documents for item hrefs. An item whose key is
# longer simply imports without one, exactly as every item did before asset
# keys were tracked; the refresh then falls back to matching on the href.
MAX_ASSET_KEY_CHARS = 255

# feat(#1692): the longest asset media type GeoLens will carry — the width of
# ``DatasetAsset.media_type`` (String(100)), where an imported item's declared
# type is persisted so the STAC items GeoLens serves can re-advertise it.
# Same capture-side bound and for the same reason as MAX_ASSET_KEY_CHARS
# above: search surfacing a type the import model would reject turns one
# unusual item into a 422 for the whole batch. Registered media types are
# nowhere near this long; an item whose type is longer simply imports
# without one.
MAX_ASSET_MEDIA_TYPE_CHARS = 100


def storable_media_type(media_type: str | None) -> str | None:
    """The asset's declared media type if it fits the column, else None.

    feat(#1692): applied at capture (search) and again where the refresh
    reads a re-fetched item, so every writer of ``DatasetAsset.media_type``
    carries the same bound the column enforces.
    """
    if not isinstance(media_type, str) or len(media_type) > MAX_ASSET_MEDIA_TYPE_CHARS:
        return None
    return media_type


def storable_asset_key(key: str | None) -> str | None:
    """The asset key if it is short enough to carry, else None.

    fix(#1331): ``""`` is a legal JSON property name and a legal STAC asset
    key, and it is deliberately NOT refused here. Every consultation of a
    stored key downstream (``stac_resolve.py``) now tests it with
    ``is not None`` rather than truthiness, which is what makes a recorded
    ``""`` mean something different from "no key recorded" — refusing it at
    capture would defeat that: a resolve that used a stored ``""`` to
    recover a moved asset would strip it back out on write-back, and the
    dataset would need to guess again the next time the asset moved. Unlike
    an over-long key, ``""`` runs into no length problem, so there is
    nothing about it worth refusing once the truthiness reads are honest.
    """
    if key is None or len(key) > MAX_ASSET_KEY_CHARS:
        return None
    return key


# The keys a published COG hides behind, in the order the import flow has
# always tried them. `data` and `visual` are the STAC-common spellings,
# `image` is the older one, and `B04` is Sentinel-2's red band — the asset a
# single-band import of that collection wants.
_PREFERRED_ASSET_KEYS: tuple[str, ...] = ("data", "visual", "image", "B04")


def pick_data_asset(assets: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The item's primary data asset, as ``(key, asset)``, or None.

    feat(#1266): extracted from ``search_stac_items`` when the refresh
    strategy needed the same choice. Import picks an asset out of a searched
    item; a refresh re-picks it out of the SAME item fetched again later, and
    the two have to agree or a refresh would quietly re-point a dataset at a
    different band. One implementation is what makes them agree.

    The KEY comes back as well as the asset because it is the durable name for
    "which asset this dataset was imported from" — hrefs move, which is the
    whole subject of #1266, and the key is what survives the move.

    Non-dict entries are skipped rather than trusted. The inline version read
    ``.get("roles")`` off every value, so a malformed catalog answering with a
    scalar asset raised inside search; here it simply does not match.
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

    feat(#1266): lifted out of :func:`self_link_href` when the refresh
    strategy needed the identical gate for an item's ASSET href. Both end up
    in ``origin_ref``, so both have to clear the same bar, and the bar is not
    a matter of taste: pydantic's ``HttpUrl`` is what the import request model
    applies, the 4096 cap is that model's field limit, and the credential
    refusal is ADR-002 invariant 4 — a signed URL must never reach the source
    binding. Writing the check twice is how one copy ends up laxer than the
    model it is supposed to mirror.

    A relative href is legal STAC, so resolution happens BEFORE any check;
    otherwise ``//user:pw@host/x`` would smuggle userinfo past a scan of the
    raw value.
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

    feat(#1222): search is the ONE place GeoLens ever holds a STAC item
    document, so it is the only place the item's own href can be captured —
    the import request carries an item id and an asset href, and neither
    composes back into the item URL for a catalog that does not follow the
    ``/collections/{c}/items/{id}`` layout. Without this, ``origin_ref``'s
    reserved ``item_href`` key stays permanently unwritten and the health
    probe can only ever check the asset, never whether the item was
    withdrawn from the catalog.

    A relative href is legal STAC (the validation fixtures accept one), so it
    is resolved against the URL the response actually came from before any
    check runs — dropping it would leave ``item_href`` unwritten and the
    health probe blind to a withdrawal on exactly the catalogs that publish
    self links most carefully (fix #1271 review). After resolution, two ways
    a link is still dropped rather than surfaced, and the second is the one
    that matters. A non-http(s) href goes because the probe would have
    nothing safe to fetch. A CREDENTIALED href goes because the import
    request validator refuses one outright (a signed URL must never reach
    ``origin_ref``, ADR-002 invariant 4) — and since search is what fills the
    field the UI echoes back, surfacing one here would turn an optional
    convenience into a 422 that fails the caller's whole import batch.
    Dropping at capture keeps the refusal for hand-crafted clients, where it
    is the right answer, and off the path GeoLens itself drives.
    """
    links = feature.get("links")
    # isinstance: a malformed scalar links value must cost only this optional
    # field, not 502 the whole search (fix #1271 review).
    for link in links if isinstance(links, list) else []:
        if not isinstance(link, dict) or link.get("rel") != "self":
            continue
        # fix(#1271 review): a malformed href must be dropped, not surfaced —
        # item_href is optional, and the frontend echoes search results into
        # the import request, where StacImportItem applies HttpUrl, the
        # credential refusal, and a 4096 cap. Surfacing anything that gate
        # rejects turns one broken link into a 422 for the caller's whole
        # batch. `storable_href` IS that gate.
        resolved = storable_href(link.get("href"), base_url)
        if resolved is not None:
            return resolved
    return None


def _make_client() -> httpx.AsyncClient:
    """Shared httpx client configuration for STAC API requests.

    Phase 1061 SEC-S04: delegates to make_safe_client() so the per-hop SSRF
    revalidation hook applies to every STAC API probe (including indirect
    redirects from /stac/.well-known/* to internal CIDRs).
    """
    return make_safe_client(timeout=STAC_TIMEOUT)


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

        # EW-05: surface STAC file:size (when present) so the frontend can show
        # an estimated download size before the user commits to a multi-GB fetch.
        data_asset_size_bytes = data_asset.get("file:size") if data_asset else None
        if not isinstance(data_asset_size_bytes, int):
            data_asset_size_bytes = None  # be defensive — bad-shape values become None

        items.append(
            {
                "id": f.get("id"),
                "collection": f.get("collection"),
                # resp.url is the LOGICAL post-redirect URL: the SSRF
                # transport restores the hostname after each pinned hop
                # (see _SSRFGuardTransport), so relative self links resolve
                # against the host the caller addressed, never the pinned IP.
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
                # feat(#1692): bounded at capture like the key below, so the
                # echoed value always fits the import model and the
                # DatasetAsset.media_type column it is persisted into.
                "data_asset_type": storable_media_type(
                    data_asset.get("type") if data_asset else None
                ),
                # feat(#1266): the durable half of the asset's identity. The
                # href is what moves; this is what still names the same asset
                # afterwards, so a refresh can follow the move instead of
                # re-running the priority list and possibly picking another.
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
