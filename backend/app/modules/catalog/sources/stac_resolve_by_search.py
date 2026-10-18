"""The by-search fallback path for STAC re-resolution.

Reached from ``stac_resolve.resolve_stac_binding`` only once the stored
``item_href`` has answered 404/410.
"""

from __future__ import annotations

from typing import Any

from app.core.service_tokens import ServiceCredential
from app.modules.catalog.sources.origin_probe import MISSING, fetch_json_document
from app.modules.catalog.sources.stac_resolve_asset_gate import _resolve_from_item
from app.modules.catalog.sources.stac_resolve_identity import (
    _search_root_and_item_id,
    credential_for_read,
)
from app.modules.catalog.sources.stac_resolve_taxonomy import (
    StacResolution,
    _SEARCH_UNUSABLE,
    _WITHDRAWN,
)


def _searched_feature(
    document: Any, *, item_id: str, collection_id: str
) -> dict[str, Any] | None:
    """The searched item, if the answer actually contains it.

    A 200 from ``/search`` isn't itself an answer about this item: an
    endpoint that ignores the filters hands back a page of the catalog, so
    both filters are re-checked against the response.

    The collection must be AFFIRMED, not merely not contradicted. An item id
    is unique only within its collection, so an endpoint honouring ``ids``
    while ignoring ``collections`` can return a same-id item elsewhere, and a
    feature omitting ``collection`` would pass the weaker contradiction test.
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
    credential: ServiceCredential | None = None,
    catalog_origin: str | None = None,
    repair_nodata: bool = False,
) -> StacResolution:
    """Look the item up by identity after its own URL stopped resolving.

    The search ROOT can only come from the URL, so a catalog outside the
    standard layout gets no second path. The IDENTITY prefers the stored id,
    which is exact, over the one read out of the URL.
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
        credential=credential_for_read(
            credential, url=search_url, credential_origin=catalog_origin
        ),
    )
    if not result.ok:
        # A search that couldn't be carried out establishes nothing and must
        # not report `missing`: the item may simply have moved.
        if result.health == MISSING:
            # "No search endpoint here" is not a fact about this item, so the
            # item's own 404 stays the last word, with its own detail.
            return _WITHDRAWN
        # contacted=True whatever the search's own flag: the item itself
        # answered 404/410, and a search failing before the wire must not
        # erase that prior contact.
        return StacResolution(result.health, result.detail, contacted=True)
    feature = _searched_feature(
        document, item_id=wanted_id, collection_id=collection_id or ""
    )
    if feature is None:
        # An empty result is authoritative (`missing`). A non-empty result
        # that doesn't match means the endpoint ignores the filters (limit:1
        # left room only for an unrelated row) and establishes nothing.
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
        credential=credential,
        catalog_origin=catalog_origin,
        repair_nodata=repair_nodata,
    )


__all__ = ["_resolve_by_search", "_searched_feature"]
