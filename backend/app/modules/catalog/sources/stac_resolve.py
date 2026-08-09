"""Re-resolve a STAC dataset's binding against the catalog that published it.

feat(#1266) / ADR-002 Amendment A10. A STAC dataset holds no bytes: the COG
lives in somebody else's bucket and Titiler reads it at tile time. So the
only thing GeoLens owns about it is a POINTER, and a pointer is exactly the
thing an upstream publisher moves — a bucket migration, a re-tiling, a
collection restructure — while the item itself carries on existing under a
new address.

#1222 taught GeoLens to NOTICE that (404/410 on the stored pointer ->
``missing``) and deliberately stopped there: a probe reports, it never
rewrites. This module is the acting half. It re-reads the item document the
asset was imported from, and reports where that item says its asset lives
now.

**It decides nothing about the database.** Every function here is a network
read that returns facts; the refresh strategy in ``processing/`` is what
persists them, under the run ledger and the binding guard. That split is why
this lives in ``catalog/sources/`` beside the probe and the import adapter —
all three fetch third-party URLs, and Rule 2's safe client, the closed health
vocabulary, and the storable-href gate are all here already.

### The two paths, and why the second one exists

The stored ``item_href`` is the first and best answer: it is the item's own
canonical URL, captured from its ``rel=self`` link at import. When it still
resolves, the item document names the asset and there is nothing to guess.

When it 404s, the item may still be alive at a NEW address — which is the
entire subject of this issue, and the case a probe cannot tell apart from a
withdrawal. So the second path re-searches for the item by identity:
collection plus item id, through the catalog's ``/search`` endpoint. That
endpoint is not an assumption — it is how the item was found in the first
place, since every STAC dataset in GeoLens came from ``search_stac_items``
posting to exactly that URL.

The search root and the item id are DERIVED from ``item_href`` rather than
stored, and derived in a way that fails closed: the href must literally
contain ``/collections/<the stored collection_id>/items/<something>``, so the
derivation is checked against a second stored value rather than assumed.
Catalogs that lay their items out some other way simply have no second path,
which is the honest outcome — nothing available says where else to look.
``datasets.source_filename`` holds the item id too and is deliberately NOT
used: it is a PATCHable field, and a user-editable value that steers which
remote item a dataset gets re-pointed at is a rebinding primitive, not a
pointer.

### What each outcome means

- the item resolves -> the asset href it names, plus the asset's own
  freshly-probed health. The probe is reused rather than assumed healthy
  because a resolution the strategy is about to STORE should be one GeoLens
  has actually contacted; adopting an unverified pointer is how a refresh
  reports success over a dataset whose tiles have stopped working.
- the item is authoritatively gone (404/410) and the re-search does not
  produce it -> ``missing``. A failed re-search does not un-say the item's
  404; it only fails to find a new home for it, which leaves the probe's own
  verdict for that exact observation standing.
- anything else — a timeout, a 5xx, a 401/403, a body that is not a STAC item
  -> ``inaccessible``. Nothing was established about the origin, and the
  caller must leave the stored pointers exactly as they are.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import structlog

from app.modules.catalog.sources.adapters.stac import (
    pick_data_asset,
    storable_asset_key,
    projection_epsg,
    self_link_href,
    storable_href,
)
from app.modules.catalog.sources.cog_info import fetch_cog_info
from app.modules.catalog.sources.origin_probe import (
    BLOCKED_BY_POLICY,
    INACCESSIBLE,
    ITEM_WITHDRAWN,
    MISSING,
    NOT_FOUND,
    UNAUTHORIZED,
    UNEXPECTED_STATUS,
    fetch_json_document,
    probe_remote_uri,
)
from app.modules.catalog.sources.security import SSRFError, validate_url_for_ssrf

logger = structlog.get_logger(__name__)

# fix(#1266 review round 5): `datasets.origin_uri` is String(2000) and the
# adopted asset href lands there. The storable-href gate above it mirrors the
# IMPORT MODEL's 4096 cap, which is the right bar for `origin_ref` (JSONB,
# unbounded) and one the column cannot hold — so a 2050-character href would
# clear every check and then abort the success transaction, failing a refresh
# that had actually resolved. Refusing it up front turns that into a verdict
# the run can explain.
_MAX_STORED_URI_CHARS = 2000


@dataclass(frozen=True)
class StacResolution:
    """Where a STAC dataset's asset lives now, and how the origin answered.

    ``health``/``detail`` are ADR-002's stored vocabulary, produced by the
    #1222 classifier rather than by a second one here.

    ``resolved`` and ``health`` are independent on purpose. An item can name
    its asset perfectly while that asset answers 404 — the publisher's
    document is authoritative about WHERE the asset is, and the probe is
    authoritative about whether it is being served. Collapsing the two would
    force a refresh to choose between adopting a correct pointer and
    reporting a true health, and both are worth recording.
    """

    health: str
    detail: str | None = None
    contacted: bool = True
    item_href: str | None = None
    # fix(#1266 review round 9): the id the resolved document answers to.
    # Written back with the rest of the binding, so a dataset whose catalog
    # states no identity in its URLs still accumulates one it can be checked
    # against next time.
    item_id: str | None = None
    asset_href: str | None = None
    asset_key: str | None = None
    # fix(#1266 review round 5): the moved object's OWN structural metadata.
    # A moved asset is not the same asset — a re-tiled scene can change its
    # band count, dtype, nodata and the statistics every rescale is computed
    # from — and the tile proxy builds `bidx`, rescale and nodata parameters
    # from what the catalog stored. Adopting the new href while keeping the
    # old object's description renders the new raster through the old one's
    # parameters. Populated only when the href moved, which is the only time
    # anything is adopted.
    asset_metadata: dict[str, Any] | None = None
    # fix(#1266 review round 7): the moved object's declared projection, read
    # from the item that publishes it rather than from the object. That is
    # where the import path reads it too — the STAC projection extension —
    # so the two agree by construction, and a reprojected replacement stops
    # being described by the previous object's EPSG. Populated beside
    # ``asset_metadata`` and written with it.
    epsg: int | None = None

    @property
    def resolved(self) -> bool:
        """Whether the publisher named where the asset lives now."""
        return self.asset_href is not None


# "The item document is gone and nothing else knows where it went." The
# detail is the probe's own word for a withdrawn item, so the refresh and the
# probe describe the same upstream event with the same code.
_WITHDRAWN = StacResolution(MISSING, ITEM_WITHDRAWN)

# "The item is there and no longer publishes an asset this dataset can use."
# Authoritative — the publisher answered — and distinct from a withdrawal,
# because the item itself is still on the catalog.
_ASSET_GONE = StacResolution(MISSING, NOT_FOUND)

# "The asset is there and GeoLens may not point at where it now lives." The
# publisher started signing hrefs, so the binding cannot be stored (ADR-002
# invariant 4). Nothing was deleted, so this is not `missing`.
_ASSET_UNUSABLE = StacResolution(INACCESSIBLE, UNAUTHORIZED)

# "The asset exists and GeoLens cannot work out its address." Only reachable
# on the search path, where the document arrived inside a FeatureCollection:
# if its self link is absent or contradicts it, there is no item URL to join
# a relative href against, and the `/search` endpoint is not a stand-in for
# one. Declining beats composing a path under the search URL and hoping
# nothing is served there.
_ASSET_UNADDRESSABLE = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

# "The publisher named a new asset and GeoLens could not read it." The item
# is fine, the address is allowed, and the object behind it did not answer as
# a COG — inconclusive, so nothing is adopted and a retry can succeed.
_ASSET_UNREADABLE = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

# "The publisher moved the asset somewhere GeoLens is not allowed to fetch."
# Not adopted, and this is a security property rather than a health one: the
# stored href is read by the raster tile path, which hands an http(s) value
# to Titiler/GDAL — and per AGENTS.md Rule 2 GDAL cannot be made
# redirect-safe from the inside, so the safe client's refusal is the only
# check that will ever run against it. Persisting an address the guard just
# rejected would launder it past the guard.
_ASSET_BLOCKED = StacResolution(INACCESSIBLE, BLOCKED_BY_POLICY)

# "The origin answered, with a document for a DIFFERENT item." Same verdict
# as the shape failure below and for the same reason — the origin answered,
# and what it said establishes nothing about THIS dataset's item — but a
# separate name because the two are separate faults to investigate.
_NOT_THIS_ITEM = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

# "The origin answered, with something that is not a STAC item." Inconclusive
# rather than authoritative: a landing page, an HTML error, or a truncated
# body says nothing about whether the item is still published.
# `unexpected_status` is already the closed vocabulary's word for it, and
# inventing a code would cost every consumer that enumerates the set.
_NOT_AN_ITEM = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)


_COLLECTIONS_SEGMENT = "/collections/"
_ITEMS_SEGMENT = "/items/"


def _standard_item_path(url: str) -> tuple[str, str, str] | None:
    """``(root, collection id, item id)`` for a URL in the standard layout.

    The one parser for "what identity does this URL state", used by both the
    fallback-search derivation and the self-link check. A URL states an
    identity only when it spells ``/collections/<c>/items/<id>`` with a single
    segment on each side; anything else — a static catalog's
    ``/scenes/x.json``, an ``/items/a/b`` that addresses something INSIDE an
    item — states none, and gets None rather than a guess.

    Segments are percent-decoded, because the path carries the encoded
    spelling while the catalog's own ``id`` and ``collection`` fields carry
    the real one.
    """
    parts = urlsplit(url)
    index = parts.path.rfind(_COLLECTIONS_SEGMENT)
    if index < 0:
        return None
    collection, separator, tail = parts.path[
        index + len(_COLLECTIONS_SEGMENT) :
    ].partition(_ITEMS_SEGMENT)
    if not separator or not collection or "/" in collection:
        return None
    item_segment = tail.strip("/")
    if not item_segment or "/" in item_segment:
        return None
    root = urlunsplit((parts.scheme, parts.netloc, parts.path[:index], "", ""))
    return root, unquote(collection), unquote(item_segment)


def _search_root_and_item_id(
    item_href: str, collection_id: str | None
) -> tuple[str, str] | None:
    """``(search root, item id)`` derived from the item's own URL, or None.

    The derivation is only permitted where the URL states the identity it is
    being read for: the collection in the path must be the one GeoLens stored
    at import. A catalog that lays items out differently, or a stored href
    whose collection disagrees with the stored one, returns None here and
    gets no second path, rather than having a root guessed for it.
    """
    if not collection_id:
        return None
    parsed = _standard_item_path(item_href)
    if parsed is None:
        return None
    root, collection, item_id = parsed
    if collection != collection_id:
        return None
    return root, item_id


def _self_link_contradicts(
    self_href: str, *, item_id: Any, collection_id: str | None
) -> bool:
    """Whether an item's ``rel=self`` link points somewhere it should not.

    fix(#1266 review round 2): the self link became load-bearing in round 1 —
    it is now the base for relative asset hrefs AND the pointer that gets
    stored — so it needs the same scrutiny as the document that carries it.
    A body whose ``id`` and ``collection`` are right while its self link
    addresses a DIFFERENT item would otherwise resolve that item's relative
    assets and, worse, persist its URL: the next refresh would then derive
    its expected identity from the wrong URL, agree with itself, and the
    dataset would have quietly walked to another scene.

    Same contradiction-not-confirmation rule as everywhere else here: a self
    link whose path states no identity (a static catalog, a permalink
    service) cannot disagree with anything and is trusted. One that states an
    identity must state THIS one.
    """
    parsed = _standard_item_path(self_href)
    if parsed is None:
        return False
    _root, collection, linked_item_id = parsed
    if isinstance(item_id, str) and linked_item_id != item_id:
        return True
    return bool(collection_id and collection != collection_id)


def _bound_asset_key(
    assets: dict[str, Any], *, asset_href: str | None, asset_key: str | None
) -> str | None:
    """WHICH asset in this item is the one the dataset is bound to.

    Three ways to recognise it, strongest first, and the order is the whole
    of the correctness argument:

    1. the stored ``asset_key`` — identity by name, and the reason the key is
       written back on every successful resolve;
    2. the asset whose href still equals the stored one — identity by value.
       This is also the unchanged case, and it recovers the key for datasets
       imported before ``asset_key`` was ever written;
    3. ``pick_data_asset`` — no identity left, so re-run the exact choice the
       import made. Weakest, and last: an item that renamed its key AND moved
       its href is indistinguishable from a fresh import, and this is what a
       fresh import would pick.

    Identity is settled here, ALONE, and specifically before the href is
    looked at. Choosing the first candidate with a usable href instead would
    mean a bound asset whose href GeoLens may not store (a publisher who
    started signing URLs) silently demoted the dataset onto whatever the
    import default happens to be today — a different band, published as a
    successful refresh. Which asset this dataset serves is not something a
    refresh gets to change.
    """
    if asset_key and isinstance(assets.get(asset_key), dict):
        return asset_key
    if asset_href:
        for key, asset in assets.items():
            if isinstance(asset, dict) and asset.get("href") == asset_href:
                return key
    picked = pick_data_asset(assets)
    return picked[0] if picked else None


def _contradicts_stored_identity(
    item: dict[str, Any],
    *,
    expected_item_id: str | None,
    collection_id: str | None,
) -> bool:
    """Whether this document says it is something OTHER than what was asked for.

    fix(#1266 review): the direct path used to accept any document carrying an
    ``assets`` object, which is not the same claim as "this is the item this
    dataset was imported from". A stored URL that redirects — a catalog that
    collapsed a scene into a mosaic, a bucket that serves a default document —
    hands back a perfectly valid item, and ``_bound_asset_key``'s last resort
    would then pick that stranger's primary asset and the worker would publish
    it as this dataset's raster. The search path never had the hole because
    ``_feature_by_id`` matches on id; this is the direct path's equivalent.

    Framed as CONTRADICTION rather than confirmation because confirmation is
    not always available: a dataset imported before ``item_id`` was recorded
    has only what its URL states, and that is nothing at all for a catalog
    outside the ``/collections/{c}/items/{id}`` layout. Where BOTH sides
    state a value they must agree; where neither does, the answer stands on
    ``item_href`` being the item's own canonical URL.

    fix(#1266 review round 9): ``expected_item_id`` now comes from the
    BINDING first and the URL only as a fallback, which is what closes the
    hole for those non-standard catalogs — a canonical URL that later serves
    a different item of the same collection used to pass this check, and the
    asset chooser would then republish that item's raster as this dataset.
    Every refresh writes the id back, so a dataset only has to be refreshed
    once to gain the identity it is checked against thereafter.
    """
    if expected_item_id is not None and item.get("id") != expected_item_id:
        return True
    stated_collection = item.get("collection")
    return bool(
        collection_id
        and isinstance(stated_collection, str)
        and stated_collection != collection_id
    )


def _absolute_http(href: Any) -> str | None:
    """*href* if it already addresses itself, else None.

    The base-free case: an absolute http(s) href needs no document URL to be
    resolved against, so it is the only shape that can be adopted when no
    trustworthy item address exists.
    """
    if not isinstance(href, str):
        return None
    return href if urlsplit(href).scheme in ("http", "https") else None


async def _resolve_from_item(
    item: dict[str, Any],
    *,
    item_base: str | None,
    document_url: str,
    fallback_item_href: str,
    expected_item_id: str | None,
    collection_id: str | None,
    asset_href: str | None,
    asset_key: str | None,
) -> StacResolution:
    """Turn a fetched item document into a resolution, health included.

    One reading of one document, used by both paths, so the direct fetch and
    the re-search cannot reach different verdicts about the same shape.
    """
    if not isinstance(item, dict):
        return _NOT_AN_ITEM
    assets = item.get("assets")
    if not isinstance(assets, dict):
        return _NOT_AN_ITEM
    if _contradicts_stored_identity(
        item, expected_item_id=expected_item_id, collection_id=collection_id
    ):
        return _NOT_THIS_ITEM
    key = _bound_asset_key(assets, asset_href=asset_href, asset_key=asset_key)
    if key is None:
        return _ASSET_GONE

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
    self_href = self_link_href(item, document_url)
    if self_href is not None and _self_link_contradicts(
        self_href, item_id=item.get("id"), collection_id=collection_id
    ):
        # Dropped rather than fatal, matching how #1222 treats every other
        # unusable self link: the document is still this item by its own id,
        # so the refresh can proceed from the URL it demonstrably came from.
        # What must not happen is storing the contradictory pointer.
        logger.info("stac_self_link_identity_mismatch", item_id=item.get("id"))
        self_href = None

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
    raw_href = assets[key].get("href")
    asset_base = self_href or item_base or _absolute_http(raw_href)
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
    resolved_item_href = await _storable_item_pointer(self_href, fallback_item_href)

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
            # Do not publish a pointer to an object GeoLens could not read.
            # Same discipline as the raster replace path's read-back: a
            # publisher's document saying where the asset is, is not the same
            # fact as that asset being openable. Inconclusive, so the stored
            # binding stays exactly as it is and a retry can succeed.
            return _ASSET_UNREADABLE

    properties = item.get("properties")
    resolved_id = item.get("id")
    return StacResolution(
        health=probed.health,
        detail=probed.detail,
        contacted=probed.contacted,
        item_href=resolved_item_href,
        item_id=resolved_id if isinstance(resolved_id, str) else None,
        asset_href=href,
        # Bounded on the way into the binding by the same rule search
        # applies on the way out of the catalog: a key too long to carry is
        # simply not carried, and the asset is still resolved — identity was
        # already settled above, and the href match will find it again.
        asset_key=storable_asset_key(key),
        asset_metadata=metadata,
        epsg=projection_epsg(properties if isinstance(properties, dict) else {}),
    )


async def _storable_item_pointer(self_href: str | None, fallback: str) -> str:
    """The item pointer to store: the new self link, or the one already held.

    fix(#1266 review round 5): a self link is not storable just because it is
    well-formed and states the right identity. It also has to be an address
    the refresh door will accept next time — that door SSRF-validates
    ``origin_ref.item_href`` before it will queue anything. A publisher that
    starts advertising a self link on a private host would otherwise get one
    successful refresh and then permanently locked-out ones, with the usable
    pointer already overwritten.

    Validated with the door's own function so the two cannot disagree. This
    resolves DNS and issues no request; the fallback needs no check, because
    it is the value that got this refresh admitted in the first place.
    """
    if self_href is None or self_href == fallback:
        return fallback
    try:
        await validate_url_for_ssrf(self_href)
    except SSRFError:
        logger.info("stac_self_link_blocked_by_policy")
        return fallback
    return self_href


def _feature_by_id(document: Any, item_id: str) -> dict[str, Any] | None:
    """The searched item, if the answer actually contains it.

    A 200 from ``/search`` is not by itself an answer about this item: an
    endpoint that ignores the ``ids`` filter would hand back the collection's
    first page, and taking ``features[0]`` from that would re-point the
    dataset at an unrelated scene. The id is re-checked here for that reason.
    """
    if not isinstance(document, dict):
        return None
    features = document.get("features")
    for feature in features if isinstance(features, list) else []:
        if isinstance(feature, dict) and feature.get("id") == item_id:
            return feature
    return None


async def _resolve_by_search(
    *,
    item_href: str,
    item_id: str | None,
    collection_id: str | None,
    asset_href: str | None,
    asset_key: str | None,
) -> StacResolution:
    """Look the item up by identity after its own URL stopped resolving.

    The search ROOT can only come from the URL — there is nowhere else to
    read it from — so a catalog outside the standard layout still gets no
    second path. The IDENTITY prefers the stored id, which is exact, over the
    one read out of the URL.
    """
    derived = _search_root_and_item_id(item_href, collection_id)
    if derived is None:
        return _WITHDRAWN
    root, derived_id = derived
    wanted_id = item_id or derived_id
    search_url = f"{root}/search"
    result, document, search_result_url = await fetch_json_document(
        search_url,
        method="POST",
        json_body={"collections": [collection_id], "ids": [wanted_id], "limit": 1},
    )
    feature = _feature_by_id(document, wanted_id) if result.ok else None
    if feature is None:
        # Either the catalog answered and does not have this item, or the
        # search could not be carried out at all. Both leave the item's own
        # 404 as the last authoritative word, which is `missing` — the same
        # verdict the probe writes for the same observation, reached without
        # the search having to prove anything.
        return _WITHDRAWN
    return await _resolve_from_item(
        feature,
        # No item base: the search endpoint is not the item's address. Only
        # the feature's own self link can supply one here.
        item_base=None,
        document_url=search_result_url,
        fallback_item_href=item_href,
        expected_item_id=wanted_id,
        collection_id=collection_id,
        asset_href=asset_href,
        asset_key=asset_key,
    )


async def resolve_stac_binding(
    *,
    item_href: str,
    item_id: str | None = None,
    collection_id: str | None = None,
    asset_href: str | None = None,
    asset_key: str | None = None,
) -> StacResolution:
    """Ask the publisher where this dataset's asset lives now.

    Pure network and pure computation: nothing here reads or writes the
    database, and the caller is free to hold no session across it.
    """
    # The identity the answer is checked against. The BINDING first — it is
    # exact, and it is the only thing a catalog outside the standard layout
    # can be checked against at all — falling back to reading the id out of
    # the URL for datasets imported before it was recorded. That fallback is
    # only ever a reading of the stored href when the href spells out the
    # collection GeoLens also stored, never a guess.
    derived = _search_root_and_item_id(item_href, collection_id)
    expected_item_id = item_id or (derived[1] if derived else None)

    result, document, item_url = await fetch_json_document(item_href)
    if result.ok:
        return await _resolve_from_item(
            document,
            # The URL this document was actually read from IS the item's
            # address on this path, redirects included.
            item_base=item_url,
            document_url=item_url,
            fallback_item_href=item_href,
            expected_item_id=expected_item_id,
            collection_id=collection_id,
            asset_href=asset_href,
            asset_key=asset_key,
        )
    if result.health == MISSING:
        return await _resolve_by_search(
            item_href=item_href,
            item_id=item_id,
            collection_id=collection_id,
            asset_href=asset_href,
            asset_key=asset_key,
        )
    # Inconclusive: a timeout, a 5xx, a 401/403, a policy refusal. Nothing was
    # established about where the asset is, so the caller keeps every stored
    # pointer and records only what it could not do.
    return StacResolution(result.health, result.detail, contacted=result.contacted)
