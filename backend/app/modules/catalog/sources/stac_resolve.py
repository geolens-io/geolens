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

### Decomposition (#1335)

The strategy outgrew one file and was split along its natural seams, with
this module kept as both the by-URL entry point (``resolve_stac_binding``,
directly below) and the façade external callers and tests import through:

- ``stac_resolve_taxonomy.py``  -- the closed verdict vocabulary and the
                                    ``StacResolution`` dataclass.
- ``stac_resolve_identity.py``  -- URL/body identity derivation and
                                    contradiction checks, shared by every path.
- ``stac_resolve_asset_gate.py``-- turns one fetched item document into a
                                    resolution: identity refusal, asset-key
                                    binding, self-link trust, and the SSRF +
                                    COG probe gate an adopted href must clear.
- ``stac_resolve_by_search.py`` -- the by-search fallback, reached only once
                                    the direct fetch below 404/410s.

Every name a caller outside this package previously imported from
``stac_resolve`` still resolves from here.
"""

from __future__ import annotations

import structlog

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
    # fix(#1266 review round 24): a binding may carry no collection at all —
    # `StacImportItem.collection` is optional and the import stores what it
    # was given — and every collection comparison here is skipped when it is
    # absent. A stored `/collections/A/items/x` that later redirects to
    # `/collections/B/items/x` would then rebind the dataset to B's keyed
    # asset. The URL states the collection even when the binding does not, so
    # it stands in for verification. It is NOT written back: the worker
    # restamps the stored value, and inventing a collection from a URL is a
    # different act from reading one to check an answer against.
    stored_layout = _standard_item_path(item_href)
    effective_collection = collection_id or (
        stored_layout[1] if stored_layout else None
    )
    derived = _search_root_and_item_id(item_href, effective_collection)
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
            collection_id=effective_collection,
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
            collection_id=effective_collection,
            asset_href=asset_href,
            asset_key=asset_key,
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
