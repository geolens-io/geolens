"""The closed verdict vocabulary for STAC re-resolution (#1335 split).

Every function in this package answers "where does this dataset's asset live
now" by returning one of the ``StacResolution`` sentinels defined here — the
dataclass and the closed set of outcomes it can carry, with no dependency on
how any of them is reached. See ``stac_resolve.py`` for the strategy's full
narrative: the two resolution paths, why the search fallback exists, and what
each outcome means to a caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.catalog.sources.origin_probe import (
    BLOCKED_BY_POLICY,
    INACCESSIBLE,
    ITEM_WITHDRAWN,
    MISSING,
    NOT_FOUND,
    UNAUTHORIZED,
    UNEXPECTED_STATUS,
)


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
    # fix(#1266 review round 24, retention half): the collection this answer
    # was checked against. A binding imported with `collection=null` — which
    # `StacImportItem` permits — has none of its own, so the stored item URL
    # stands in; reporting it back lets the binding LEARN it, the same way
    # `item_id` is learned, and a dataset that refreshes once is checked
    # against a stored value thereafter instead of a re-derived one.
    collection_id: str | None = None
    asset_href: str | None = None
    asset_key: str | None = None
    # feat(#1692): the bound asset's declared media type, read from the same
    # document the href came from. It repairs the served `dataset_assets`
    # row's media_type on every successful refresh — the import echoes the
    # value search captured, and a dataset imported before either existed
    # learns it the first time it refreshes. Bounded by storable_media_type
    # at the gate, so it always fits the column it is written into.
    asset_media_type: str | None = None
    # fix(#1266 review round 5): the moved object's OWN structural metadata.
    # A moved asset is not the same asset — a re-tiled scene can change its
    # band count, dtype, nodata and the statistics every rescale is computed
    # from — and the tile proxy builds `bidx`, rescale and nodata parameters
    # from what the catalog stored. Adopting the new href while keeping the
    # old object's description renders the new raster through the old one's
    # parameters. Populated only when the href moved, which is the only time
    # anything is adopted.
    asset_metadata: dict[str, Any] | None = None
    # fix(#1266 review round 7): the moved object's projection — read from
    # the item that publishes it when nothing better is available, which is
    # where the import path reads it too, so an unmoved asset's EPSG still
    # agrees with the import that set it.
    #
    # fix(#1334 review): reconciled with the probe's OWN CRS when one ran —
    # see ``reconcile_epsg``. The item's declaration is the publisher's
    # CLAIM about the object; ``asset_metadata`` (when populated) came from
    # Titiler actually opening the CURRENT bytes, which is ground truth.
    # A stale item declaration disagreeing with the probed CRS used to
    # reach the caller as this field regardless, and the caller pairs it
    # with ``asset_metadata["crs_wkt"]`` when writing both to one row —
    # publishing two contradictory projections for the same raster. This
    # field is the single authoritative value once a probe has run, and
    # ``asset_metadata["epsg"]`` remains the RAW probe reading beside it.
    epsg: int | None = None
    # fix(#1266 review round 25): the moved object's footprint. A publisher
    # who re-tiles or crops a scene updates the item's bbox with it, and a
    # dataset that goes on advertising the old one lies to every spatial
    # search and map-bounds read — the same lie the registered-table strategy
    # corrects when it clears an emptied table's extent. Carried from the
    # same document as the asset, so the two cannot describe different
    # objects. None when the item states none, which is not a statement that
    # the footprint changed.
    bbox: list[float] | None = None

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


__all__ = [
    "StacResolution",
    "_ASSET_BLOCKED",
    "_ASSET_GONE",
    "_ASSET_UNADDRESSABLE",
    "_ASSET_UNIDENTIFIED",
    "_ASSET_UNREADABLE",
    "_ASSET_UNUSABLE",
    "_NOT_AN_ITEM",
    "_NOT_THIS_ITEM",
    "_SEARCH_UNUSABLE",
    "_UNVERIFIABLE",
    "_WITHDRAWN",
]
