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
    self_link_href,
    storable_href,
)
from app.modules.catalog.sources.origin_probe import (
    INACCESSIBLE,
    ITEM_WITHDRAWN,
    MISSING,
    NOT_FOUND,
    UNAUTHORIZED,
    UNEXPECTED_STATUS,
    fetch_json_document,
    probe_remote_uri,
)

logger = structlog.get_logger(__name__)


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
    asset_href: str | None = None
    asset_key: str | None = None

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


def _search_root_and_item_id(
    item_href: str, collection_id: str | None
) -> tuple[str, str] | None:
    """``(search root, item id)`` derived from the item's own URL, or None.

    The derivation is only permitted where the URL states the identity it is
    being read for: the path must contain ``/collections/<collection_id>/
    items/<id>`` with the collection id GeoLens stored at import. A catalog
    that lays items out differently returns None here and gets no second
    path, rather than having a root guessed for it.

    Query and fragment are dropped before the split — they belong to the
    request, not to the item's identity — and the id is percent-decoded,
    because the path segment is the encoded spelling of it while ``/search``
    matches on the real one.
    """
    if not collection_id:
        return None
    parts = urlsplit(item_href)
    marker = f"/collections/{collection_id}/items/"
    index = parts.path.rfind(marker)
    if index < 0:
        return None
    segment = parts.path[index + len(marker) :]
    # One segment, or this is not an item URL: `/items/a/b` addresses
    # something inside the item, and re-searching for `a` would bind the
    # dataset to a different resource than the one it points at.
    if not segment or "/" in segment.strip("/"):
        return None
    item_id = unquote(segment.strip("/"))
    root = urlunsplit((parts.scheme, parts.netloc, parts.path[:index], "", ""))
    return root, item_id


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

    Framed as CONTRADICTION rather than confirmation, deliberately, because
    confirmation is not always available. The item id can only be read out of
    ``item_href`` where the catalog uses the standard layout, so requiring it
    would refuse to refresh every catalog that does not — the same catalogs
    that already get no fallback search. What is always available is the
    weaker but sound test: where BOTH sides state a value, they must agree.
    A document that states a different id, or a different collection, is not
    this item and is refused; one that states neither is accepted on the
    strength of the stored ``item_href`` being the item's own canonical URL,
    which is what #1222 captured it from.
    """
    if expected_item_id is not None and item.get("id") != expected_item_id:
        return True
    stated_collection = item.get("collection")
    return bool(
        collection_id
        and isinstance(stated_collection, str)
        and stated_collection != collection_id
    )


async def _resolve_from_item(
    item: dict[str, Any],
    *,
    item_url: str,
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
    self_href = self_link_href(item, item_url)
    asset_base = self_href or item_url

    # A relative asset href is legal STAC, so it is resolved against that base
    # and then put through the same gate as every other value that reaches
    # ``origin_ref``.
    href = storable_href(assets[key].get("href"), asset_base)
    if href is None:
        # The item is published and still carries this asset; GeoLens simply
        # may not point at where it now lives — a signed URL is the case that
        # matters, and ADR-002 invariant 4 forbids storing one. "Access lost,
        # resource intact" is exactly what `unauthorized` means in this
        # vocabulary, and it is emphatically not `missing`: nothing was
        # deleted and the stored pointer may well still serve.
        return _ASSET_UNUSABLE
    # The item's CURRENT self link, so a re-search that found the item at a
    # new address updates the pointer that failed. Falls back to the pointer
    # already stored: a catalog that publishes no self link has told GeoLens
    # nothing better to point at, and inventing an address from the search
    # endpoint would store one no reader could resolve.
    resolved_item_href = self_href or fallback_item_href
    probed = await probe_remote_uri(href)
    return StacResolution(
        health=probed.health,
        detail=probed.detail,
        contacted=probed.contacted,
        item_href=resolved_item_href,
        asset_href=href,
        asset_key=key,
    )


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
    collection_id: str | None,
    asset_href: str | None,
    asset_key: str | None,
) -> StacResolution:
    """Look the item up by identity after its own URL stopped resolving."""
    derived = _search_root_and_item_id(item_href, collection_id)
    if derived is None:
        return _WITHDRAWN
    root, item_id = derived
    search_url = f"{root}/search"
    result, document, search_result_url = await fetch_json_document(
        search_url,
        method="POST",
        json_body={"collections": [collection_id], "ids": [item_id], "limit": 1},
    )
    feature = _feature_by_id(document, item_id) if result.ok else None
    if feature is None:
        # Either the catalog answered and does not have this item, or the
        # search could not be carried out at all. Both leave the item's own
        # 404 as the last authoritative word, which is `missing` — the same
        # verdict the probe writes for the same observation, reached without
        # the search having to prove anything.
        return _WITHDRAWN
    return await _resolve_from_item(
        feature,
        item_url=search_result_url,
        fallback_item_href=item_href,
        expected_item_id=item_id,
        collection_id=collection_id,
        asset_href=asset_href,
        asset_key=asset_key,
    )


async def resolve_stac_binding(
    *,
    item_href: str,
    collection_id: str | None = None,
    asset_href: str | None = None,
    asset_key: str | None = None,
) -> StacResolution:
    """Ask the publisher where this dataset's asset lives now.

    Pure network and pure computation: nothing here reads or writes the
    database, and the caller is free to hold no session across it.
    """
    # The identity the answer is checked against, where the URL states one.
    # Same derivation the fallback search uses, for the same reason: it is
    # only a reading of the stored href when that href spells out the
    # collection GeoLens also stored, never a guess.
    derived = _search_root_and_item_id(item_href, collection_id)
    expected_item_id = derived[1] if derived else None

    result, document, item_url = await fetch_json_document(item_href)
    if result.ok:
        return await _resolve_from_item(
            document,
            item_url=item_url,
            fallback_item_href=item_href,
            expected_item_id=expected_item_id,
            collection_id=collection_id,
            asset_href=asset_href,
            asset_key=asset_key,
        )
    if result.health == MISSING:
        return await _resolve_by_search(
            item_href=item_href,
            collection_id=collection_id,
            asset_href=asset_href,
            asset_key=asset_key,
        )
    # Inconclusive: a timeout, a 5xx, a 401/403, a policy refusal. Nothing was
    # established about where the asset is, so the caller keeps every stored
    # pointer and records only what it could not do.
    return StacResolution(result.health, result.detail, contacted=result.contacted)
