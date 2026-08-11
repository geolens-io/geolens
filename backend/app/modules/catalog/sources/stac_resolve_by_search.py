"""The by-search fallback path for STAC re-resolution (#1335 split).

Reached from ``stac_resolve.resolve_stac_binding`` only once the stored
``item_href`` has 404/410'd — see that module's docstring for why the second
path exists at all and what a searched answer is and is not allowed to prove.
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


__all__ = ["_resolve_by_search", "_searched_feature"]
