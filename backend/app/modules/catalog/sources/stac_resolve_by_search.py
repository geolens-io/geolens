"""The by-search fallback path for STAC re-resolution.

Reached from ``stac_resolve.resolve_stac_binding`` only once the stored
``item_href`` has 404/410'd — see that module's docstring for what a
searched answer is and isn't allowed to prove.
"""

from __future__ import annotations

from typing import Any

from app.modules.catalog.sources.origin_probe import MISSING, fetch_json_document
from app.modules.catalog.sources.stac_resolve_asset_gate import _resolve_from_item
from app.modules.catalog.sources.stac_resolve_identity import _search_root_and_item_id
from app.modules.catalog.sources.stac_resolve_taxonomy import (
    StacResolution,
    _SEARCH_UNUSABLE,
    _WITHDRAWN,
)


def _searched_feature(
    document: Any, *, item_id: str, collection_id: str
) -> dict[str, Any] | None:
    """The searched item, if the answer actually contains it.

    A 200 from ``/search`` isn't itself an answer about this item — an
    endpoint that ignores the filters hands back a page of the catalog, so
    both filters are re-checked against the response.

    fix(#1266): the collection must be AFFIRMED, not merely not contradicted.
    An item id is unique only within its collection, so an endpoint honouring
    ``ids`` while ignoring ``collections`` can legitimately return a same-id
    item elsewhere, and a feature omitting ``collection`` would otherwise
    sail through the weaker contradiction test used elsewhere.
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
        # fix(#1266): a search that couldn't be carried out establishes
        # nothing and must not report `missing` — the item may simply have
        # moved, which is the whole reason the search exists.
        if result.health == MISSING:
            # fix(#1266): "no search endpoint here" is not a fact about this
            # item, so the item's own 404 stays the last word with its own
            # detail, not the search endpoint's not_found.
            return _WITHDRAWN
        # fix(#1266): contacted=True regardless of the search's own flag —
        # this function is only reached because the item itself answered
        # 404/410, so the origin demonstrably responded; a search failing
        # before the wire must not erase that prior contact.
        return StacResolution(result.health, result.detail, contacted=True)
    feature = _searched_feature(
        document, item_id=wanted_id, collection_id=collection_id or ""
    )
    if feature is None:
        # fix(#1266): an empty result is authoritative (`missing`). A
        # non-empty result that doesn't match means the endpoint isn't
        # honouring the filters (limit:1 means an unrelated row is all it
        # had room to return) and establishes nothing about this item.
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


__all__ = ["_resolve_by_search", "_searched_feature"]
