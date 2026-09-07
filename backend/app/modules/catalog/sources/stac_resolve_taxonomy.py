"""The closed verdict vocabulary for STAC re-resolution.

Every function in this package answers "where does this dataset's asset live
now" by returning one of the ``StacResolution`` sentinels defined here. See
``stac_resolve.py`` for the two resolution paths and what each outcome means
to a caller.
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

    ``health``/``detail`` are ADR-002's stored vocabulary (#1222 classifier).

    Resolution and health are independent on purpose: an item can name its
    asset perfectly while that asset 404s. The publisher's document is
    authoritative about where the asset is; the probe is authoritative about
    whether it's being served. Both are worth recording separately.
    """

    health: str
    detail: str | None = None
    contacted: bool = True
    item_href: str | None = None
    # fix(#1266): written back with the binding, so a dataset whose catalog
    # states no identity in its URLs still accumulates one to check against.
    item_id: str | None = None
    # fix(#1266): a binding imported with collection=null has none of its
    # own, so the stored item URL stands in; reporting it back lets the
    # binding learn it and be checked against a stored value thereafter.
    collection_id: str | None = None
    asset_href: str | None = None
    asset_key: str | None = None
    # feat(#1692): repairs the served dataset_assets row's media_type on
    # every successful refresh, bounded by storable_media_type at the gate.
    asset_media_type: str | None = None
    # fix(#1266): a moved asset is not the same asset — re-tiling can change
    # band count/dtype/nodata/stats, which the tile proxy builds
    # bidx/rescale/nodata from. Populated only when the href moved.
    asset_metadata: dict[str, Any] | None = None
    # fix(#1266): read from the item when nothing better is available,
    # matching where import reads it.
    #
    # fix(#1334): reconciled with the probe's own CRS when one ran (see
    # reconcile_epsg) — the item's declaration is the publisher's claim,
    # asset_metadata (when populated) is Titiler's ground truth from
    # opening the current bytes. This field is the single authoritative
    # value once a probe has run; asset_metadata["epsg"] stays the raw
    # probe reading beside it.
    epsg: int | None = None
    # fix(#1266): a publisher who re-tiles/crops updates the item's bbox;
    # carried from the same document as the asset so the two describe the
    # same object. None when the item states none — not a claim it changed.
    bbox: list[float] | None = None

    @property
    def resolved(self) -> bool:
        """Whether the publisher named where the asset lives now."""
        return self.asset_href is not None


# "The search endpoint answered, and not about what was asked." A page that
# ignores the filters, or a body that isn't a feature list, proves nothing.
_SEARCH_UNUSABLE = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

# "GeoLens cannot tell this item from another one the same URL might serve."
# Nothing fetched or written; not a health verdict.
_UNVERIFIABLE = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS, contacted=False)

# "The item document is gone and nothing else knows where it went."
_WITHDRAWN = StacResolution(MISSING, ITEM_WITHDRAWN)

# "The item publishes assets and none is provably this dataset's." Reached
# when a keyless binding's recorded href has moved — GeoLens won't guess.
_ASSET_UNIDENTIFIED = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

# "The item is there and no longer publishes an asset this dataset can use."
# Distinct from withdrawal — the item itself is still on the catalog.
_ASSET_GONE = StacResolution(MISSING, NOT_FOUND)

# "The asset is there and GeoLens may not store where it now lives" (e.g. a
# signed href, forbidden by ADR-002 invariant 4). Not `missing`.
_ASSET_UNUSABLE = StacResolution(INACCESSIBLE, UNAUTHORIZED)

# "The asset exists and GeoLens cannot work out its address." Only reachable
# on the search path with no usable self link to resolve a relative href
# against; declining beats composing a path under /search and hoping.
_ASSET_UNADDRESSABLE = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

# "The publisher named a new asset and GeoLens could not read it." Item and
# address are fine; inconclusive, so nothing adopted and a retry can succeed.
_ASSET_UNREADABLE = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

# "The publisher moved the asset somewhere GeoLens is not allowed to fetch."
# A security property, not a health one: the tile path hands the stored href
# to Titiler/GDAL, which Rule 2 (AGENTS.md) cannot make redirect-safe
# internally, so persisting a rejected address would launder it past the
# only guard that checks it.
_ASSET_BLOCKED = StacResolution(INACCESSIBLE, BLOCKED_BY_POLICY)

# "The origin answered, with a document for a DIFFERENT item."
_NOT_THIS_ITEM = StacResolution(INACCESSIBLE, UNEXPECTED_STATUS)

# "The origin answered, with something that is not a STAC item." Inconclusive
# (landing page, HTML error, truncated body) — not authoritative.
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
