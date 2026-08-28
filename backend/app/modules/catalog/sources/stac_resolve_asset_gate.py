"""Turn a fetched STAC item document into a resolution (#1335 split).

This is the asset gate: one reading of one item document, shared by the
by-URL path (``stac_resolve.py``) and the by-search fallback
(``stac_resolve_by_search.py``) so the two cannot reach different verdicts
about the same shape. It settles identity, binds the asset key, resolves the
item's own self link, and — the SSRF + COG probe half the module is named
for — validates and reads back the moved object before anything is adopted.
"""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlsplit

import structlog

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

# fix(#1266 review round 5): `datasets.origin_uri` is String(2000) and the
# adopted asset href lands there. The storable-href gate above it mirrors the
# IMPORT MODEL's 4096 cap, which is the right bar for `origin_ref` (JSONB,
# unbounded) and one the column cannot hold — so a 2050-character href would
# clear every check and then abort the success transaction, failing a refresh
# that had actually resolved. Refusing it up front turns that into a verdict
# the run can explain.
_MAX_STORED_URI_CHARS = 2000


def _bound_asset_key(
    assets: dict[str, Any], *, asset_href: str | None, asset_key: str | None
) -> str | None:
    """WHICH asset in this item is the one the dataset is bound to, or None.

    Two ways to recognise it, and both are identity rather than inference:

    1. the stored ``asset_key`` — identity by name, and the reason the key is
       written back on every successful resolve;
    2. the asset whose href still equals the stored one — identity by value.
       This is also the unchanged case, and it is what recovers the key for a
       dataset imported before ``asset_key`` was recorded: one refresh while
       the href still resolves and the binding is named from then on.

    fix(#1266 review round 11): there is deliberately no third way. Re-running
    ``pick_data_asset`` — the import's own priority list — used to be the
    fallback, and for a keyless binding whose href has ALREADY moved it is a
    guess wearing the clothes of a rule: an item imported from ``visual`` that
    has since gained a ``data`` asset would be switched to ``data``, served as
    that, and recorded as that. Reported as a successful refresh. The failure
    nobody notices.

    Identity is settled here alone, and the caller refuses when it comes back
    None. Which asset a dataset serves is not something a refresh may decide.

    fix(#1331): the key is read with ``is not None``, not truthiness. ``""``
    is a legal JSON property name and a legal asset key, and capture (see
    ``storable_asset_key``) preserves it and distinguishes it from no key at
    all — a binding that recorded it names a real asset, and treating it
    like no key was recorded is exactly the bug this reads honestly instead
    of reintroducing.
    """
    if asset_key is not None and isinstance(assets.get(asset_key), dict):
        return asset_key
    if asset_href:
        for key, asset in assets.items():
            if isinstance(asset, dict) and asset.get("href") == asset_href:
                return key
    return None


def _absolute_http(href: Any) -> str | None:
    """*href* if it already addresses itself, else None.

    The base-free case: an absolute http(s) href needs no document URL to be
    resolved against, so it is the only shape that can be adopted when no
    trustworthy item address exists.
    """
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

    Extracted so the identity rules read as one gate rather than as branches
    interleaved with asset resolution — every round of review has added one,
    and they belong together.

    Three questions, and the third is why they cannot be collapsed: does the
    BODY state an identity other than the stored one; does the URL the
    document CAME from state one (round 17 — that URL is the base relative
    asset hrefs resolve against, so a redirect into another collection's
    same-id item steers the asset); and, when NOTHING trustworthy states the
    collection, does the body affirm it.

    That last one closes the permalink case (fix #1266 review round 18). A
    non-standard item URL states no collection, so a permalink re-pointed at
    another collection's same-id item, in a body that omits its optional
    ``collection`` field, has nothing anywhere to contradict — and the bound
    key would then select the other collection's asset. Where no URL can
    speak for the collection, the document has to.
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
) -> StacResolution:
    """Turn a fetched item document into a resolution, health included.

    One reading of one document, used by both paths, so the direct fetch and
    the re-search cannot reach different verdicts about the same shape.
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
        # fix(#1266 review round 18): a binding that RECORDED its key knows
        # exactly which entry disappeared, so its absence is a removed asset
        # and reports as one — even when the item still publishes something
        # the import rule would have picked. Only a keyless binding is
        # genuinely unable to tell removal from ambiguity.
        #
        # fix(#1331): `is not None`, not truthiness — the same reasoning as
        # `_bound_asset_key` above. A binding that recorded `""` still
        # recorded a key, and treating it as keyless here would report a
        # removed asset as an unidentified one instead.
        if asset_key is not None:
            return _ASSET_GONE
        # Two different facts, and they read differently to whoever acts on
        # them. An item that publishes no usable data asset at all has lost
        # the asset — authoritative, and `missing` is the honest verdict. An
        # item that publishes one GeoLens cannot prove is this dataset's has
        # lost nothing; GeoLens has simply run out of ways to identify it,
        # which is a refusal rather than a verdict about the origin.
        if pick_data_asset(assets) is None:
            return _ASSET_GONE
        return _ASSET_UNIDENTIFIED

    # fix(#1266 review): the item's OWN address is the base for its relative
    # hrefs, and it is resolved first because the asset resolution depends on
    # it. On the search path the document arrived inside a FeatureCollection,
    # so ``item_url`` is the ``/search`` endpoint — joining a legal relative
    # asset href against THAT composes a path under the search URL rather
    # than under the item, which is a different object and possibly a live
    # one. RFC 3986 would allow either reading; STAC's is the item's own
    # location, and it is also the only one that survives the item moving.
    # The requested URL stays the fallback for catalogs that publish no self
    # link — it is where this document demonstrably came from.
    #
    # fix(#1266 review round 20): the self link is settled ONCE, before it is
    # used for anything. It steers two things — the base relative asset hrefs
    # resolve against, and the pointer that gets stored — and validating it
    # only on the way to storage left the first one reading from an untrusted
    # URL, so an item advertising a login page could still have a COG resolved
    # under that page's path and persisted as this dataset's asset.
    self_href, self_base, self_document = await _trustworthy_self_href(
        item,
        document_url=document_url,
        fallback=fallback_item_href,
        # The direct path fetched the fallback to get this document; the
        # search path is here because that fetch returned 404/410.
        fallback_is_live=item_base is not None,
        collection_id=collection_id,
        asset_key=key,
    )

    # fix(#1266 review round 4): ``item_base`` is the item's own address when
    # the caller has one — the URL the document was fetched from on the direct
    # path, and NOTHING on the search path, where the document arrived inside
    # a FeatureCollection and the `/search` endpoint addresses the query
    # rather than the item. Round 1 fixed the trusted-self-link case; this is
    # the same bug one branch over, reached when the self link is absent or
    # was just dropped as contradictory. With no trustworthy item URL, a
    # relative href cannot be resolved at all — joining it against `/search`
    # composes a path under the query endpoint, and the danger is precisely
    # that something might be served there.
    # fix(#1266 review round 23): one binding, one document. When a
    # canonical address was adopted above, the asset is read from what THAT
    # address serves — storing one document's pointer beside another
    # document's href would have this run adopt the first's asset while the
    # next run, reading the pointer it was handed, switched to the second's.
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
        # The item is published and still carries this asset; GeoLens simply
        # may not point at where it now lives — a signed URL is the case that
        # matters, and ADR-002 invariant 4 forbids storing one. "Access lost,
        # resource intact" is exactly what `unauthorized` means in this
        # vocabulary, and it is emphatically not `missing`: nothing was
        # deleted and the stored pointer may well still serve.
        return _ASSET_UNUSABLE
    if len(href) > _MAX_STORED_URI_CHARS:
        return _ASSET_UNADDRESSABLE

    # The item's CURRENT self link, so a re-search that found the item at a
    # new address updates the pointer that failed. Falls back to the pointer
    # already stored: a catalog that publishes no self link has told GeoLens
    # nothing better to point at, and inventing an address from the search
    # endpoint would store one no reader could resolve.
    resolved_item_href = self_href or fallback_item_href

    probed = await probe_remote_uri(href)
    if probed.detail == BLOCKED_BY_POLICY:
        # fix(#1266 review round 4): refused, not merely reported. Every other
        # probe verdict is a fact about the origin that the binding can carry
        # — an asset that 404s is still where the publisher says it is. This
        # one is a fact about GEOLENS: the address is one the SSRF guard will
        # not fetch, at the first hop or somewhere down a redirect chain. The
        # raster tile path hands a stored http(s) `asset_uri` to Titiler/GDAL,
        # which AGENTS.md Rule 2 is explicit cannot be made redirect-safe from
        # the inside, so adopting this href would put an address past the only
        # guard that ever checks it.
        return _ASSET_BLOCKED

    metadata: dict[str, Any] | None = None
    if href != asset_href:
        # fix(#1266 review round 5): the moved object describes itself, and
        # the catalog has to be re-told. A re-tiled scene can change its band
        # count, dtype, nodata and per-band statistics, and the tile proxy
        # builds `bidx`, rescale and nodata from what was stored — so a new
        # single-band COG served through the old three-band description
        # renders wrong or fails outright.
        #
        # Read only when the href MOVED, which is the only time anything is
        # adopted. An object replaced in place at an unchanged URL is the
        # raster twin of the registered-table case: the owner rewrote what
        # GeoLens points at, no pointer changed, and re-reading on every
        # refresh would buy a Titiler round trip per refresh for it.
        #
        # Gate 1 of `fetch_cog_info`'s documented dual gate: the URL is
        # SSRF-validated by its CALLER before Titiler is handed it. The probe
        # above already refused a blocked address, and this is the explicit
        # standalone call that contract asks for.
        try:
            await validate_url_for_ssrf(href)
        except SSRFError:
            return _ASSET_BLOCKED
        metadata = await fetch_cog_info(href)
        if metadata is None:
            # fix(#1266 review round 24): the probe may already have settled
            # this. An href that answers 404/410 is conclusively gone, and
            # Titiler being unable to describe a missing object adds nothing —
            # replacing that verdict with an inconclusive one would throw away
            # the one fact the run established about the publisher's new
            # asset. The pointer is still not adopted either way.
            if probed.health == MISSING:
                return StacResolution(probed.health, probed.detail)
            # Do not publish a pointer to an object GeoLens could not read.
            # Same discipline as the raster replace path's read-back: a
            # publisher's document saying where the asset is, is not the same
            # fact as that asset being openable. Inconclusive, so the stored
            # binding stays exactly as it is and a retry can succeed.
            return _ASSET_UNREADABLE

    # From the same document as the asset (fix #1266 review round 24): a
    # canonical document that supersedes the representation supersedes its
    # projection too, and writing the other one's EPSG would describe the
    # wrong object in STAC output and in VRT compatibility checks.
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
        # Bounded on the way into the binding by the same rule search
        # applies on the way out of the catalog: a key too long to carry is
        # simply not carried, and the asset is still resolved — identity was
        # already settled above, and the href match will find it again.
        asset_key=storable_asset_key(key),
        # feat(#1692): from the same document as the href — the refresh
        # writes it onto the served `dataset_assets` row, so what GeoLens
        # re-advertises is what the publisher currently declares.
        asset_media_type=storable_media_type(describing["assets"][key].get("type")),
        asset_metadata=metadata,
        # fix(#1334 review): reconciled here, once, where both facts are in
        # hand — `reconcile_epsg({}, declared_epsg)` for an unmoved asset
        # (metadata is None) is just `declared_epsg`, so this is a no-op
        # change for that case and the caller (processing/) never needs to
        # import anything to get the same preference for a moved one.
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
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """``(pointer to store, base for relative hrefs, the document at it)``.

    fix(#1266 review round 22): two values, because the self link plays two
    roles and they do not always name the same URL. The POINTER is the
    address the publisher declares as canonical. The BASE is the address the
    document was actually SERVED from, which is what RFC 3986 and STAC both
    resolve relative hrefs against — and under a redirect those differ. A
    document served from a new directory while still declaring the old self
    link would otherwise resolve its relative assets under the stale
    directory, and a COG sitting at that sibling path would be adopted.

    One decision for the two things a self link steers: the base that
    relative asset hrefs resolve against, and the pointer that gets stored.
    Settled before either is computed (fix #1266 review round 20) — checking
    it on the way to storage alone left the base reading from an untrusted
    URL, and a COG resolved under a login page's path is a worse outcome
    than a stale pointer.

    Three questions, each from a round of review:

    - does the URL itself state an identity other than the stored one;
    - does it SERVE this item — the next refresh's own first step, run
      against it, because a 200 from an auth wall is not the same claim;
    - does the document it serves still carry the asset this dataset is
      bound to. The item is what a pointer addresses, but the asset is what
      the dataset needs, and an address that has the item without the asset
      is one the next refresh cannot get anything from.

    The document comes back with the pointer (fix #1266 review round 23)
    because the two have to describe each other. When a canonical address is
    adopted, the ASSET has to be read from the document that address serves —
    otherwise a refresh stores one document's pointer beside another
    document's href, this run adopts `old.tif`, and the next run, reading the
    pointer it was handed, switches to `new.tif`. One binding, one document.

    A None pointer means "keep what you have": the document in hand is still
    this item, so the refresh proceeds from the URL it demonstrably came
    from, and the working pointer is not overwritten. Dropped rather than
    fatal, matching how #1222 treats every other unusable self link. A None
    base means the caller's own document URL is the better one.
    """
    self_href = self_link_href(item, document_url)
    if self_href is None:
        return None, None, None
    if self_href == fallback and fallback_is_live:
        # Nothing to prove: this is the URL the document was just fetched
        # from. fix(#1266 review round 21): only on the direct path. The
        # search path is reached BECAUSE the stored pointer 404s, so a
        # searched feature advertising that same stale URL must still be
        # checked — skipping it would make a known-dead address the base a
        # relative asset href resolves against.
        #
        # No base comes back with it (fix #1266 review round 22): this URL is
        # the one the caller ASKED for, and the caller's `item_base` is the
        # one that answered. Under a redirect those differ, and the relative
        # hrefs belong to the address that served the document.
        return self_href, None, None
    if _url_contradicts_identity(
        self_href, item_id=item.get("id"), collection_id=collection_id
    ):
        logger.info("stac_self_link_identity_mismatch", item_id=item.get("id"))
        return None, None, None
    result, document, final_url = await fetch_json_document(self_href)
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
        # fix(#1266 review round 21): present is not the same as usable. A
        # STAC Asset Object requires an href, and a keyed empty object gives
        # the next refresh nothing to resolve — which it would then report as
        # an unusable asset, again without reaching the search fallback.
        storable_href(replacement_asset.get("href"), final_url) is None
    ):
        logger.info("stac_self_link_lacks_the_bound_asset", asset_key=asset_key)
        return None, None, None
    # The final URL, not the declared one: this fetch may have redirected
    # too, and the base is always where the document came from.
    return self_href, final_url, document


def _horizontal_bbox(stated: Any) -> list[float] | None:
    """``[west, south, east, north]`` from a STAC bbox, or None.

    fix(#1266 review round 26): a bbox may be SIX values —
    ``minx, miny, minz, maxx, maxy, maxz`` — which GeoJSON and STAC both
    allow and this repository already handles in ``parse_bbox``. Taking the
    first four of those reads the elevation as east and the longitude as
    north, and writes a corrupted extent. The horizontal pair is at indices
    0, 1, 3, 4 in the 3D form and 0, 1, 2, 3 in the 2D one; anything else
    states no footprint this can use.
    """
    if not isinstance(stated, list) or len(stated) not in (4, 6):
        return None
    indices = (0, 1, 2, 3) if len(stated) == 4 else (0, 1, 3, 4)
    values = [stated[index] for index in indices]
    # `math.isfinite` mirrors SEC-FU-06 in `parse_bbox` (fix #1266 review
    # round 27): JSON `1e400` parses as infinity and the NaN extension is
    # commonly accepted, PostGIS handles neither consistently, and either
    # would reach `ST_GeomFromText` — failing a refresh that had otherwise
    # resolved, or persisting a malformed extent.
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
