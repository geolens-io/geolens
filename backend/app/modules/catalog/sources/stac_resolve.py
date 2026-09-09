"""Re-resolve a STAC dataset's binding against the catalog that published it.

feat(#1266)/ADR-002 A10. A STAC dataset holds no bytes, only a POINTER an
upstream publisher can move. #1222 taught GeoLens to NOTICE that (404/410 ->
``missing``) but not to act; this module is the acting half — every function
here is a network read that returns facts, never writes to the DB. The
refresh strategy in ``processing/`` persists what this reports, under the
run ledger and binding guard.

Two resolution paths: the stored ``item_href`` (the item's ``rel=self`` link
captured at import) is tried first. If it 404s, a fallback re-search looks
the item up by collection + item id, both DERIVED from ``item_href`` and
checked against the stored ``collection_id`` — failing closed for catalogs
laid out differently, rather than trusting ``datasets.source_filename``,
which is user-PATCHable and therefore not a safe rebinding input.

Outcomes: item resolves -> its asset href plus a fresh health probe (reused
rather than assumed healthy, since a stored resolution should be one GeoLens
actually contacted). Item is gone and the re-search also fails -> ``missing``.
Anything else (timeout, 5xx, 401/403, non-STAC body) -> ``inaccessible``,
and the caller leaves stored pointers untouched.

Decomposition (#1335): this module is the by-URL entry point
(``resolve_stac_binding``) and the façade external callers/tests import
through. ``stac_resolve_taxonomy.py`` holds the verdict vocabulary;
``stac_resolve_identity.py`` the URL/body identity checks shared by every
path; ``stac_resolve_asset_gate.py`` turns a fetched item into a resolution
(identity refusal, asset-key binding, self-link trust, SSRF/COG gate);
``stac_resolve_by_search.py`` is the by-search fallback.
"""

from __future__ import annotations

import structlog

from app.core.service_tokens import ServiceCredential
from app.modules.catalog.sources.origin_probe import MISSING, fetch_json_document
from app.modules.catalog.sources.stac_resolve_asset_gate import (
    _bound_asset_key,  # noqa: F401 -- re-exported, see __all__
    _horizontal_bbox,  # noqa: F401 -- re-exported, see __all__
    _resolve_from_item,
)
from app.modules.catalog.sources.stac_resolve_by_search import _resolve_by_search
from app.modules.catalog.sources.stac_resolve_identity import (
    _search_root_and_item_id,
    _standard_item_path,
    states_verifiable_identity,  # noqa: F401 -- re-exported, see __all__
)
from app.modules.catalog.sources.stac_resolve_taxonomy import (
    StacResolution,
    _ASSET_BLOCKED,  # noqa: F401 -- re-exported, see __all__
    _ASSET_GONE,  # noqa: F401 -- re-exported, see __all__
    _ASSET_UNADDRESSABLE,  # noqa: F401 -- re-exported, see __all__
    _ASSET_UNIDENTIFIED,  # noqa: F401 -- re-exported, see __all__
    _ASSET_UNREADABLE,  # noqa: F401 -- re-exported, see __all__
    _ASSET_UNUSABLE,  # noqa: F401 -- re-exported, see __all__
    _NOT_AN_ITEM,  # noqa: F401 -- re-exported, see __all__
    _NOT_THIS_ITEM,  # noqa: F401 -- re-exported, see __all__
    _SEARCH_UNUSABLE,  # noqa: F401 -- re-exported, see __all__
    _UNVERIFIABLE,
    _WITHDRAWN,  # noqa: F401 -- re-exported, see __all__
)

logger = structlog.get_logger(__name__)


async def resolve_stac_binding(
    *,
    item_href: str,
    item_id: str | None = None,
    collection_id: str | None = None,
    asset_href: str | None = None,
    asset_key: str | None = None,
    credential: ServiceCredential | None = None,
) -> StacResolution:
    """Ask the publisher where this dataset's asset lives now.

    Pure network and pure computation: nothing here reads or writes the
    database, and the caller is free to hold no session across it.

    feat(#1764): the refresh door stashes ``credential`` for one attempt and
    the worker claims it once. Every read below carries it, so the item
    document, the fallback search, the self link and the asset probe all
    speak to the catalog as the same caller.
    """
    # The BINDING is checked first (exact); falls back to reading the id out
    # of the URL for datasets imported before it was recorded — only ever a
    # reading of the stored href, never a guess.
    #
    # fix(#1266): `collection` is optional on a binding, and every
    # collection comparison here is skipped when absent — so a stored
    # `/collections/A/items/x` that later redirects to `/collections/B/...`
    # would rebind to B's keyed asset unless the URL's own collection stands
    # in for verification. Read only, never written back.
    stored_layout = _standard_item_path(item_href)
    effective_collection = collection_id or (
        stored_layout[1] if stored_layout else None
    )
    derived = _search_root_and_item_id(item_href, effective_collection)
    expected_item_id = item_id or (derived[1] if derived else None)
    if expected_item_id is None:
        # Nothing to check an answer against, so nothing is asked or adopted
        # — same refusal the door gives before a job exists, at the one
        # place that decides, so a direct caller can't route around it.
        logger.info("stac_identity_unverifiable")
        return _UNVERIFIABLE

    result, document, item_url = await fetch_json_document(
        item_href, credential=credential
    )
    if result.ok:
        return await _resolve_from_item(
            document,
            # The URL this document was actually read from IS the item's
            # address on this path, redirects included.
            item_base=item_url,
            document_url=item_url,
            fallback_item_href=item_href,
            expected_item_id=expected_item_id,
            collection_id=effective_collection,
            # Only a standard-layout URL speaks for the collection; a
            # permalink does not, and then the body has to.
            collection_affirmed=_standard_item_path(item_url) is not None,
            asset_href=asset_href,
            asset_key=asset_key,
            credential=credential,
        )
    if result.health == MISSING:
        return await _resolve_by_search(
            item_href=item_href,
            item_id=item_id,
            collection_id=effective_collection,
            asset_href=asset_href,
            asset_key=asset_key,
            credential=credential,
        )
    # Inconclusive: a timeout, a 5xx, a 401/403, a policy refusal. Nothing was
    # established about where the asset is, so the caller keeps every stored
    # pointer and records only what it could not do.
    return StacResolution(result.health, result.detail, contacted=result.contacted)


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
    "_bound_asset_key",
    "_horizontal_bbox",
    "_search_root_and_item_id",
    "_standard_item_path",
    "_WITHDRAWN",
    "resolve_stac_binding",
    "states_verifiable_identity",
]
