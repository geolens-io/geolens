"""Identity derivation and contradiction checks shared across STAC re-resolution (#1335 split).

Both the by-URL path (``stac_resolve.py``) and the by-search fallback
(``stac_resolve_by_search.py``) need to ask "what identity does this URL or
document state, and does it disagree with what GeoLens already knows" — this
module is the one place those questions are answered, so the two paths and
the asset gate (``stac_resolve_asset_gate.py``) cannot reach different
answers about the same URL or document.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

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


__all__ = [
    "_contradicts_stored_identity",
    "_search_root_and_item_id",
    "_standard_item_path",
    "_url_contradicts_identity",
    "states_verifiable_identity",
]
