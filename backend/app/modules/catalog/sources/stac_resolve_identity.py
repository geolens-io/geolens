"""Identity derivation and contradiction checks shared across STAC re-resolution.

Both the by-URL path (``stac_resolve.py``) and the by-search fallback
(``stac_resolve_by_search.py``) ask "what identity does this URL or document
state, and does it disagree with what GeoLens already knows" — this module
is the one place those questions are answered, so both paths and the asset
gate (``stac_resolve_asset_gate.py``) reach the same answer.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

_COLLECTIONS_SEGMENT = "/collections/"
_ITEMS_SEGMENT = "/items/"


def _standard_item_path(url: str) -> tuple[str, str, str] | None:
    """``(root, collection id, item id)`` for a URL in the standard layout.

    A URL states an identity only when it spells
    ``/collections/<c>/items/<id>`` with a single segment on each side;
    anything else (a static catalog's ``/scenes/x.json``, an ``/items/a/b``
    addressing something inside an item) gets None rather than a guess.

    Segments are percent-decoded: the path carries the encoded spelling
    while the catalog's own ``id``/``collection`` fields carry the real one.
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

    Only permitted where the URL states the identity it's read for: the
    collection in the path must match the one stored at import. A catalog
    laid out differently, or a disagreeing stored collection, returns None
    rather than a guessed root.
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

    Asked of both a ``rel=self`` link (the stored pointer and asset-href
    base) and the post-redirect fetch URL (the base when self link is
    absent), since both steer where relative asset hrefs resolve.

    fix(#1266): a body whose id/collection are right while its self link
    addresses a different item would otherwise resolve that item's relative
    assets and persist its URL — the next refresh would then derive its
    expected identity from the wrong URL and quietly walk to another scene.

    Contradiction, not confirmation: a self link stating no identity (static
    catalog, permalink service) is trusted; one stating an identity must
    state this one.
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

    fix(#1266): a binding written before ``item_id`` was recorded, whose
    catalog publishes permalink-style URLs that state no identity either,
    has nothing to check the first answer against — a re-pointed permalink
    would be adopted and its unrelated id recorded as durable truth,
    self-consistent forever. This is a precondition, not a verdict: a
    refresh won't adopt a binding whose identity it cannot verify. Costs
    those pre-existing datasets the capability until re-imported.

    ``datasets.source_filename`` holds the same id but is deliberately not a
    fallback: it's in the metadata PATCH field map, so an edited field could
    decide which remote item a dataset is re-pointed at.
    """
    return (
        bool(item_id) or _search_root_and_item_id(item_href, collection_id) is not None
    )


def _contradicts_stored_identity(
    item: dict[str, Any],
    *,
    expected_item_id: str | None,
    collection_id: str | None,
) -> bool:
    """Whether this document says it is something OTHER than what was asked for.

    fix(#1266): a stored URL that redirects (a catalog that collapsed a
    scene into a mosaic, a bucket serving a default document) hands back a
    perfectly valid but wrong item; without this check the asset chooser's
    last resort would publish a stranger's asset as this dataset's raster.
    The search path never had this hole since ``_feature_by_id`` matches on
    id; this is the direct path's equivalent.

    Framed as contradiction, not confirmation: confirmation isn't always
    available (a pre-``item_id`` binding on a non-standard catalog has
    nothing to check). Where both sides state a value they must agree.

    fix(#1266): ``expected_item_id`` comes from the binding first, URL only
    as fallback — otherwise a canonical URL later serving a different item
    of the same collection would pass. Every refresh writes the id back, so
    one refresh is enough to gain a durable identity to check against.
    """
    if expected_item_id is not None and item.get("id") != expected_item_id:
        return True
    stated_collection = item.get("collection")
    return bool(
        collection_id
        and isinstance(stated_collection, str)
        and stated_collection != collection_id
    )


__all__ = [
    "_contradicts_stored_identity",
    "_search_root_and_item_id",
    "_standard_item_path",
    "_url_contradicts_identity",
    "states_verifiable_identity",
]
