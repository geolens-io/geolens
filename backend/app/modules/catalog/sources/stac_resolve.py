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


# "The search endpoint answered, and not about what was asked." A page that
# ignores the filters — or a body that is not a feature list — proves nothing
# about this item, and specifically not its absence.
_SEARCH_UNUSABLE = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

# "GeoLens cannot tell this item from another one the same URL might serve."
# Nothing is fetched and nothing is written — see `states_verifiable_identity`
# for why this refusal exists and why it is not a health verdict.
_UNVERIFIABLE = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS, contacted=False)

# "The item document is gone and nothing else knows where it went." The
# detail is the probe's own word for a withdrawn item, so the refresh and the
# probe describe the same upstream event with the same code.
_WITHDRAWN = StacResolution(MISSING, ITEM_WITHDRAWN)

# "The item publishes assets and none of them is provably this dataset's."
# Reached when a binding recorded no asset key and the href it did record has
# moved — nothing left to recognise the asset by. Not a health verdict: the
# origin is fine and nothing was deleted, GeoLens just will not guess which
# asset a dataset serves. One refresh while the href still resolves records
# the key and the dataset never lands here again.
_ASSET_UNIDENTIFIED = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

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


def _url_contradicts_identity(
    self_href: str, *, item_id: Any, collection_id: str | None
) -> bool:
    """Whether a URL states an identity other than the stored one.

    Asked of two URLs, for the same reason each time: both end up steering
    something. A ``rel=self`` link becomes the stored pointer and the base
    for relative assets; the URL a document was actually FETCHED from
    becomes that base too when the self link is absent or dropped.

    fix(#1266 review round 2): the self link became load-bearing in round 1 —
    it is now the base for relative asset hrefs AND the pointer that gets
    stored — so it needs the same scrutiny as the document that carries it.
    fix(#1266 review round 17): and so does the post-redirect document URL,
    for exactly the same reason one round later.
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


def states_verifiable_identity(
    *, item_href: str, item_id: str | None, collection_id: str | None
) -> bool:
    """Whether a refresh could tell this item from another one.

    fix(#1266 review round 10): the residue of the previous round. Once the
    binding carries ``item_id`` every new import is checkable, and a dataset
    that refreshes once LEARNS its id — but the learning itself has to be
    trustworthy, and for one population it is not: a binding written before
    the id was recorded, whose catalog publishes permalink-style item URLs
    that state no identity either. For those there is nothing to check the
    first answer against, so a permalink that has since been re-pointed
    would be adopted and its unrelated id recorded as durable truth. The
    wrong binding would then be self-consistent forever.

    So this is a precondition rather than a verdict: a refresh will not adopt
    a binding whose identity it cannot verify. It costs those datasets the
    new capability until they are re-imported, which is a narrower rollout of
    something new rather than the loss of something that worked — nothing
    could refresh a STAC dataset before this feature at all. Every catalog
    that lays items out as ``/collections/{c}/items/{id}`` is unaffected,
    because its URLs state the identity, and every dataset imported from here
    on is unaffected, because its binding does.

    ``datasets.source_filename`` holds the same id and is deliberately not a
    way out: it is in the metadata PATCH's field map, so backfilling from it
    would let an edited field decide which remote item a dataset is
    re-pointed at — the exact substitution this refusal exists to prevent.
    """
    return (
        bool(item_id) or _search_root_and_item_id(item_href, collection_id) is not None
    )


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
    """
    if asset_key and isinstance(assets.get(asset_key), dict):
        return asset_key
    if asset_href:
        for key, asset in assets.items():
            if isinstance(asset, dict) and asset.get("href") == asset_href:
                return key
    return None


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
        if asset_key:
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
    self_href = await _trustworthy_self_href(
        item,
        document_url=document_url,
        fallback=fallback_item_href,
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


async def _trustworthy_self_href(
    item: dict[str, Any],
    *,
    document_url: str,
    fallback: str,
    collection_id: str | None,
    asset_key: str,
) -> str | None:
    """The item's advertised address, if it can be trusted, else None.

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

    None means "keep what you have": the document in hand is still this
    item, so the refresh proceeds from the URL it demonstrably came from, and
    the working pointer is not overwritten. Dropped rather than fatal,
    matching how #1222 treats every other unusable self link.
    """
    self_href = self_link_href(item, document_url)
    if self_href is None or self_href == fallback:
        return None if self_href is None else self_href
    if _url_contradicts_identity(
        self_href, item_id=item.get("id"), collection_id=collection_id
    ):
        logger.info("stac_self_link_identity_mismatch", item_id=item.get("id"))
        return None
    result, document, final_url = await fetch_json_document(self_href)
    if not result.ok:
        logger.info("stac_self_link_not_adopted", detail=result.detail)
        return None
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
        return None
    if not isinstance(document.get("assets", {}).get(asset_key), dict):
        logger.info("stac_self_link_lacks_the_bound_asset", asset_key=asset_key)
        return None
    return self_href


def _searched_feature(
    document: Any, *, item_id: str, collection_id: str
) -> dict[str, Any] | None:
    """The searched item, if the answer actually contains it.

    A 200 from ``/search`` is not by itself an answer about this item: an
    endpoint that ignores the filters hands back a page of the catalog, and
    taking ``features[0]`` from that would re-point the dataset at an
    unrelated scene. So both filters are re-checked against the response.

    fix(#1266 review round 13): the collection is checked as well as the id,
    and it must be AFFIRMED rather than merely not contradicted. A STAC item
    id is only unique within its collection, so an endpoint that honours
    ``ids`` while ignoring ``collections`` can legitimately return a
    same-id item belonging to somewhere else — and a feature that omits its
    ``collection`` field would sail through the contradiction test that
    guards every other path here. On this path the stronger rule is the
    right one: the request named a collection, so an answer that does not
    say it is in that collection has not answered the question asked.
    """
    if not isinstance(document, dict):
        return None
    features = document.get("features")
    for feature in features if isinstance(features, list) else []:
        if not isinstance(feature, dict) or feature.get("id") != item_id:
            continue
        if feature.get("collection") == collection_id:
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
    if not result.ok:
        # fix(#1266 review round 13): a search that could not be CARRIED OUT
        # establishes nothing, and must not be reported as one that looked
        # and found nothing. Round 1 collapsed the two on the reasoning that
        # the item's own 404 was authoritative anyway — but the verdict it
        # writes is `missing`, and `missing` is exactly what this codebase
        # refuses to conclude from an inconclusive attempt everywhere else.
        # The item may simply have moved, which is the whole reason the
        # search exists.
        if result.health == MISSING:
            # fix(#1266 review round 14): the catalog answered "there is no
            # search endpoint here", which is not a fact about this item —
            # so the ITEM's own 404 stays the last word, WITH its own
            # detail. Returning the search endpoint's `not_found` instead
            # would put a verdict about the wrong resource in front of the
            # user: the Source panel would say the source was not found
            # where it should say the item was withdrawn.
            return _WITHDRAWN
        # Inconclusive about where the asset is. `contacted` is True and not
        # the search's flag (fix #1266 review round 14): this function is
        # only reached because the ITEM answered 404/410, so the origin
        # demonstrably responded — and a search that fails before it reaches
        # the wire (a DNS timeout, a first-hop policy refusal) reports
        # contacted=False about ITSELF, which must not erase a contact that
        # already happened. `last_checked_at` records that GeoLens reached
        # the origin at all, and it did.
        return StacResolution(result.health, result.detail, contacted=True)
    feature = _searched_feature(
        document, item_id=wanted_id, collection_id=collection_id or ""
    )
    if feature is None:
        # fix(#1266 review round 15): an EMPTY result is the catalog saying
        # it has no such item, which is authoritative and the one case that
        # earns `missing`. A NON-empty result that does not match is the
        # opposite: the request asked for one id in one collection and got
        # something else back, so the endpoint is not honouring the filters
        # and its answer establishes nothing about this item — least of all
        # its absence, since `limit: 1` means an unrelated first row is all
        # it ever had room to return. A body that is not a feature list says
        # as little.
        features = document.get("features") if isinstance(document, dict) else None
        if isinstance(features, list) and not features:
            return _WITHDRAWN
        return _SEARCH_UNUSABLE
    return await _resolve_from_item(
        feature,
        # No item base: the search endpoint is not the item's address. Only
        # the feature's own self link can supply one here.
        item_base=None,
        document_url=search_result_url,
        fallback_item_href=item_href,
        expected_item_id=wanted_id,
        collection_id=collection_id,
        # `_searched_feature` already required the feature to affirm it.
        collection_affirmed=True,
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
    if expected_item_id is None:
        # Nothing to check an answer against, so nothing is asked and nothing
        # is adopted. The door refuses this binding before a job exists; this
        # is the same refusal at the one place that decides, so a direct
        # caller cannot route around it.
        logger.info("stac_identity_unverifiable")
        return _UNVERIFIABLE

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
            # Only a standard-layout URL speaks for the collection; a
            # permalink does not, and then the body has to.
            collection_affirmed=_standard_item_path(item_url) is not None,
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
