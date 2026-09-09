"""Turn a fetched STAC item document into a resolution.

The asset gate: one reading of one item document, shared by the by-URL path
(``stac_resolve.py``) and the by-search fallback
(``stac_resolve_by_search.py``) so both reach the same verdict for the same
shape. Settles identity, binds the asset key, resolves the item's own self
link, and validates/reads back the moved object (SSRF + COG probe) before
anything is adopted.
"""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlsplit

import structlog

from app.core.service_tokens import ServiceCredential
from app.modules.catalog.sources.adapters.stac import (
    pick_data_asset,
    projection_epsg,
    self_link_href,
    storable_asset_key,
    storable_href,
    storable_media_type,
)
from app.modules.catalog.sources.cog_info import fetch_cog_info, reconcile_epsg
from app.modules.catalog.sources.origin_probe import (
    BLOCKED_BY_POLICY,
    MISSING,
    fetch_json_document,
    probe_remote_uri,
)
from app.platform.security import SSRFError, validate_url_for_ssrf
from app.modules.catalog.sources.stac_resolve_identity import (
    _contradicts_stored_identity,
    _standard_item_path,
    _url_contradicts_identity,
    credential_for_read,
)
from app.modules.catalog.sources.stac_resolve_taxonomy import (
    StacResolution,
    _ASSET_BLOCKED,
    _ASSET_GONE,
    _ASSET_UNADDRESSABLE,
    _ASSET_UNIDENTIFIED,
    _ASSET_UNREADABLE,
    _ASSET_UNUSABLE,
    _NOT_AN_ITEM,
    _NOT_THIS_ITEM,
)

logger = structlog.get_logger(__name__)

# fix(#1266): datasets.origin_uri is String(2000); the import model's 4096
# cap (right for JSONB origin_ref) is too loose here and would let a long
# href pass this gate then abort the success transaction on commit.
_MAX_STORED_URI_CHARS = 2000


def _bound_asset_key(
    assets: dict[str, Any], *, asset_href: str | None, asset_key: str | None
) -> str | None:
    """Which asset in this item the dataset is bound to, or None.

    Two ways to recognise it, both identity rather than inference: the stored
    ``asset_key`` by name, or the asset whose href still equals the stored
    one (also recovers the key for a pre-``asset_key`` import).

    fix(#1266): no third way. Falling back to ``pick_data_asset`` for a
    keyless binding whose href has moved would silently switch which asset
    is served and report it as a successful refresh.

    fix(#1331): checks ``is not None``, not truthiness — ``""`` is a legal
    asset key and must not be treated as no key recorded.
    """
    if asset_key is not None and isinstance(assets.get(asset_key), dict):
        return asset_key
    if asset_href:
        for key, asset in assets.items():
            if isinstance(asset, dict) and asset.get("href") == asset_href:
                return key
    return None


def _absolute_http(href: Any) -> str | None:
    if not isinstance(href, str):
        return None
    return href if urlsplit(href).scheme in ("http", "https") else None


def _identity_refusal(
    item: Any,
    *,
    document_url: str,
    expected_item_id: str | None,
    collection_id: str | None,
    collection_affirmed: bool,
) -> StacResolution | None:
    """The refusal this document earns on identity alone, or None to proceed.

    Three checks: does the body state an identity other than the stored one;
    does the document's source URL state one (it's the base relative asset
    hrefs resolve against, so a redirect into another collection's same-id
    item steers the asset); and, when nothing trustworthy states the
    collection, does the body affirm it.

    fix(#1266): that last check closes the permalink case — a non-standard
    item URL states no collection, so a permalink re-pointed at another
    collection's same-id item, with a body that omits `collection`, would
    otherwise have nothing to contradict it and the bound key would select
    the wrong collection's asset.
    """
    if not isinstance(item, dict):
        return _NOT_AN_ITEM
    if not isinstance(item.get("assets"), dict):
        return _NOT_AN_ITEM
    if _contradicts_stored_identity(
        item, expected_item_id=expected_item_id, collection_id=collection_id
    ):
        return _NOT_THIS_ITEM
    if _url_contradicts_identity(
        document_url, item_id=item.get("id"), collection_id=collection_id
    ):
        return _NOT_THIS_ITEM
    if collection_id and not collection_affirmed:
        if item.get("collection") != collection_id:
            return _NOT_THIS_ITEM
    return None


async def _resolve_from_item(
    item: dict[str, Any],
    *,
    item_base: str | None,
    document_url: str,
    fallback_item_href: str,
    expected_item_id: str | None,
    collection_id: str | None,
    collection_affirmed: bool,
    asset_href: str | None,
    asset_key: str | None,
    credential: ServiceCredential | None = None,
    credential_origin: str | None = None,
) -> StacResolution:
    """Turn a fetched item document into a resolution, health included.

    One reading of one document, used by both paths, so the direct fetch and
    the re-search cannot reach different verdicts about the same shape.

    fix(#1764): the two reads this gate makes of its own go to addresses THIS
    DOCUMENT named, so each is gated on ``credential_origin`` — the self link
    is dropped rather than fetched off-origin, and an off-origin asset is
    probed anonymously, which is the ordinary shape for a catalog whose
    assets live in someone else's bucket.
    """
    refusal = _identity_refusal(
        item,
        document_url=document_url,
        expected_item_id=expected_item_id,
        collection_id=collection_id,
        collection_affirmed=collection_affirmed,
    )
    if refusal is not None:
        return refusal
    assets = item["assets"]
    key = _bound_asset_key(assets, asset_href=asset_href, asset_key=asset_key)
    if key is None:
        # fix(#1266): a binding that recorded its key knows which entry
        # disappeared, so its absence reports as removed even if the item
        # publishes something the import rule would have picked. A keyless
        # binding cannot tell removal from ambiguity, so it falls through.
        # fix(#1331): `is not None`, not truthiness — `""` is a recorded key.
        if asset_key is not None:
            return _ASSET_GONE
        # An item with no usable data asset has lost the asset (`missing`).
        # One GeoLens cannot identify has lost nothing; it's a refusal, not
        # a verdict about the origin.
        if pick_data_asset(assets) is None:
            return _ASSET_GONE
        return _ASSET_UNIDENTIFIED

    # fix(#1266): the item's own address is the base for its relative hrefs.
    # On the search path the document arrived inside a FeatureCollection, so
    # the request URL is the /search endpoint — resolving a relative href
    # against that composes a path under the search URL, a different and
    # possibly live object. STAC's reading is the item's own location; the
    # requested URL is only the fallback for catalogs with no self link.
    #
    # fix(#1266): the self link is settled once, before use, because it
    # steers both the asset-href base and the stored pointer — validating
    # only on the way to storage would let an item advertising a login page
    # have a COG resolved under that page's path and persisted as the asset.
    self_href, self_base, self_document = await _trustworthy_self_href(
        item,
        document_url=document_url,
        fallback=fallback_item_href,
        fallback_is_live=item_base is not None,
        collection_id=collection_id,
        asset_key=key,
        credential=credential,
        credential_origin=credential_origin,
    )

    # fix(#1266): `item_base` is the item's own fetch URL on the direct path
    # and nothing on the search path (there the request URL addresses the
    # query, not the item) — with no trustworthy item URL a relative href
    # cannot be resolved at all.
    # fix(#1266): one binding, one document — the asset is read from whatever
    # document supplied the adopted self href, never a different document's
    # href stored beside it.
    describing = self_document if self_document is not None else item
    raw_href = describing["assets"][key].get("href")
    asset_base = self_base or item_base or _absolute_http(raw_href)
    if asset_base is None:
        return _ASSET_UNADDRESSABLE

    # A relative asset href is legal STAC, so it is resolved against that base
    # and then put through the same gate as every other value that reaches
    # ``origin_ref``.
    href = storable_href(raw_href, asset_base)
    if href is None:
        # Item is published and still carries this asset, but GeoLens may
        # not store where it lives (e.g. a signed URL, forbidden by ADR-002
        # invariant 4) — access lost, resource intact, not `missing`.
        return _ASSET_UNUSABLE
    if len(href) > _MAX_STORED_URI_CHARS:
        return _ASSET_UNADDRESSABLE

    # Falls back to the stored pointer: a catalog with no self link gives
    # nothing better, and inventing one from the search endpoint would be
    # unresolvable.
    resolved_item_href = self_href or fallback_item_href

    # fix(#1764): the asset href is the item's own choice of address and is
    # legitimately on another origin (a catalog's bucket), so it is probed
    # anonymously there rather than refused; the verdict is then the truth
    # about what GeoLens can read.
    probed = await probe_remote_uri(
        href,
        credential=credential_for_read(
            credential, url=href, credential_origin=credential_origin
        ),
    )
    if probed.detail == BLOCKED_BY_POLICY:
        # fix(#1266): refused, not merely reported — this is a fact about
        # GeoLens (the SSRF guard won't fetch this address, at the first hop
        # or down a redirect chain), unlike other probe verdicts which are
        # facts about the origin. The tile path hands a stored asset_uri to
        # Titiler/GDAL, which Rule 2 (AGENTS.md) cannot make redirect-safe
        # internally, so adopting this href bypasses the only guard for it.
        return _ASSET_BLOCKED

    metadata: dict[str, Any] | None = None
    if href != asset_href:
        # fix(#1266): re-read only when the href moved — a re-tiled scene can
        # change band count/dtype/nodata/stats, which the tile proxy builds
        # bidx/rescale/nodata from, so a stale description can render wrong.
        # An object replaced in place at an unchanged URL needs no re-read.
        #
        # Gate 1 of fetch_cog_info's dual gate: URL is SSRF-validated by its
        # caller before Titiler is handed it (the probe above already did).
        try:
            await validate_url_for_ssrf(href)
        except SSRFError:
            return _ASSET_BLOCKED
        # feat(#1764): Titiler fetches this URL itself, in another process,
        # so a credentialed asset that MOVED reads as unreadable rather than
        # re-describing. Carrying a key to the tiler is overlay work.
        metadata = await fetch_cog_info(href)
        if metadata is None:
            # fix(#1266): the probe may have already settled this — 404/410
            # is conclusively gone, so keep that verdict rather than replace
            # it with an inconclusive one. Pointer is not adopted either way.
            if probed.health == MISSING:
                return StacResolution(probed.health, probed.detail)
            # Do not publish a pointer to an object GeoLens could not read;
            # inconclusive, so the stored binding is unchanged and a retry
            # can succeed.
            return _ASSET_UNREADABLE

    # fix(#1266): properties/bbox read from the same document as the asset —
    # a canonical document that supersedes the representation supersedes its
    # projection too.
    properties = describing.get("properties")
    usable_bbox = _horizontal_bbox(describing.get("bbox"))
    resolved_id = item.get("id")
    declared_epsg = projection_epsg(properties if isinstance(properties, dict) else {})
    return StacResolution(
        health=probed.health,
        detail=probed.detail,
        contacted=probed.contacted,
        item_href=resolved_item_href,
        item_id=resolved_id if isinstance(resolved_id, str) else None,
        collection_id=collection_id,
        asset_href=href,
        # A key too long to carry is simply not carried; the asset is still
        # resolved since identity is already settled and the href match
        # will find it again.
        asset_key=storable_asset_key(key),
        # feat(#1692): from the same document as the href, so the refresh
        # advertises what the publisher currently declares.
        asset_media_type=storable_media_type(describing["assets"][key].get("type")),
        asset_metadata=metadata,
        epsg=reconcile_epsg(metadata or {}, declared_epsg),
        bbox=usable_bbox,
    )


async def _trustworthy_self_href(
    item: dict[str, Any],
    *,
    document_url: str,
    fallback: str,
    fallback_is_live: bool,
    collection_id: str | None,
    asset_key: str,
    credential: ServiceCredential | None = None,
    credential_origin: str | None = None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """``(pointer to store, base for relative hrefs, the document at it)``.

    fix(#1266): two values because the self link plays two roles that can
    name different URLs under a redirect — the POINTER is the publisher's
    declared canonical address, the BASE is the address the document was
    actually served from (what relative hrefs resolve against). Settled
    before either is used: checking only on the way to storage would let a
    COG resolve under an untrusted URL (e.g. a login page's path).

    Three checks: does the URL state a different identity; does it actually
    serve this item (a 200 from an auth wall doesn't count); does the
    document it serves still carry the bound asset.

    fix(#1266): the document comes back paired with the pointer so a refresh
    never stores one document's pointer beside another document's href —
    one binding, one document.

    A None pointer means keep the working one (dropped, not fatal, matching
    #1222 for every other unusable self link). A None base means the
    caller's own document URL is the better base.
    """
    self_href = self_link_href(item, document_url)
    if self_href is None:
        return None, None, None
    if self_href == fallback and fallback_is_live:
        # fix(#1266): only on the direct path — the search path is reached
        # because the stored pointer 404s, so a searched feature advertising
        # that same stale URL must still be checked, not skipped.
        # No base returned: this is the caller-requested URL, not
        # necessarily where item_base answered from under a redirect.
        return self_href, None, None
    if _url_contradicts_identity(
        self_href, item_id=item.get("id"), collection_id=collection_id
    ):
        logger.info("stac_self_link_identity_mismatch", item_id=item.get("id"))
        return None, None, None
    # fix(#1764): a self link off the catalog's origin is DROPPED, not
    # fetched anonymously: an anonymous answer about a credentialed catalog
    # is evidence for a different request than the one the refresh makes,
    # and the pointer it would replace is optional. Same rule and same
    # reason as the OGC API probe's conformance link.
    self_credential = credential_for_read(
        credential, url=self_href, credential_origin=credential_origin
    )
    if credential is not None and self_credential is None:
        logger.info("stac_self_link_off_catalog_origin")
        return None, None, None
    result, document, final_url = await fetch_json_document(
        self_href, credential=self_credential
    )
    if not result.ok:
        logger.info("stac_self_link_not_adopted", detail=result.detail)
        return None, None, None
    stated_id = item.get("id")
    refusal = _identity_refusal(
        document,
        document_url=final_url,
        expected_item_id=stated_id if isinstance(stated_id, str) else None,
        collection_id=collection_id,
        collection_affirmed=_standard_item_path(final_url) is not None,
    )
    if refusal is not None:
        logger.info("stac_self_link_does_not_serve_this_item")
        return None, None, None
    replacement_asset = document.get("assets", {}).get(asset_key)
    if not isinstance(replacement_asset, dict) or (
        # fix(#1266): present is not usable — a keyed empty object gives the
        # next refresh no href to resolve.
        storable_href(replacement_asset.get("href"), final_url) is None
    ):
        logger.info("stac_self_link_lacks_the_bound_asset", asset_key=asset_key)
        return None, None, None
    # The final URL, not the declared one: this fetch may have redirected
    # too, and the base is always where the document came from.
    return self_href, final_url, document


def _horizontal_bbox(stated: Any) -> list[float] | None:
    """``[west, south, east, north]`` from a STAC bbox, or None.

    fix(#1266): a bbox may be 6 values (minx, miny, minz, maxx, maxy, maxz);
    taking the first four would read elevation as east and longitude as
    north. Horizontal pair is at indices 0,1,3,4 in the 3D form, 0,1,2,3 in
    the 2D one.
    """
    if not isinstance(stated, list) or len(stated) not in (4, 6):
        return None
    indices = (0, 1, 2, 3) if len(stated) == 4 else (0, 1, 3, 4)
    values = [stated[index] for index in indices]
    # fix(#1266): math.isfinite mirrors SEC-FU-06 in parse_bbox — JSON
    # 1e400/NaN would reach ST_GeomFromText and persist a malformed extent.
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        for value in values
    ):
        return None
    return [float(value) for value in values]


__all__ = [
    "_MAX_STORED_URI_CHARS",
    "_absolute_http",
    "_bound_asset_key",
    "_horizontal_bbox",
    "_identity_refusal",
    "_resolve_from_item",
    "_trustworthy_self_href",
]
