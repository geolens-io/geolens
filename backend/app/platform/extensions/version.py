"""Extension API version contract for GeoLens overlay compatibility.

``EXTENSION_API_VERSION`` is an **integer** that increments whenever a Protocol
signature or registry contract changes in a way that requires overlay updates.

Bump convention
---------------
Bump this constant (and update overlay packages before re-releasing core) when:

- A required method is added to or removed from any Protocol in ``protocols.py``.
- A registry key is renamed or its expected type changes.
- The ``register_extensions(registry)`` calling convention changes.
- A single-slot vs. additive-slot classification changes for an existing key.

**Do NOT bump** for new optional methods, new registry keys overlays may
optionally populate, or internal implementation changes with no contract
impact.

Overlay declaration
-------------------
Each overlay **should** declare, as a module-level attribute in its
``register_extensions`` module::

    from app.platform.extensions.version import EXTENSION_API_VERSION

The loader reads it via ``getattr(loader, "EXTENSION_API_VERSION", None)``
and calls ``check_extension_api_version()`` before invoking the overlay. An
overlay that doesn't declare a version is treated as legacy/version-0 and
loads with a WARNING; only a declared-but-mismatched version is a hard
failure.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: v2 adds required ConnectorExtension discovery/dispatch methods and makes
#: the existing ``connectors`` registry key conflict-guarded as a single slot.
#
# 2 -> 3 (feat(#683)): ProcessingPort.run_analysis_preview gained an optional
# ``mask_dataset`` keyword (chat clips a layer by another layer). Optional
# with a default, so unimplementing overlays are unaffected, but any overlay
# that DOES implement the method must accept the new keyword.
#
# 3 -> 4 (feat(#1068)): PermissionExtension gained a required
# ``record_audience`` method — the audience-shaped reading of the same
# policy ``filter_visible``/``can_access_dataset`` already express. An
# overlay replacing the ``permission`` slot must implement it, and must keep
# it in sync whenever it changes either of those two: core can't tell a
# missing answer from a wrong one, so it takes the conservative refusal.
#
# 4 -> 5 (fix(#1314)): ProcessingPort gained a required
# ``reconcile_distributions`` method, called by the registered-PostGIS
# refresh and the reupload swap whenever dataset modality changes. An
# overlay missing it loads cleanly, then raises AttributeError inside the
# write transaction of the first refresh that matters.
#
# 5 -> 6 (refactor(stac)): CatalogPort gained a required
# ``fetch_raster_meta_bulk_without_vrt`` method (the STAC router reads
# raster meta through the port instead of importing processing ORM). Called
# on every STAC item/item-page response, including empty pages; an overlay
# missing it raises AttributeError on the first STAC request.
#
# 6 -> 7 (fix(GH-1443)): ProcessingPort gained a required
# ``get_retired_table_name_orm_class`` method — ``generate_table_name``
# lives in processing/ and needs this accessor to probe a catalog model it
# can't import directly. Called on every ingest/analysis-output/layer
# materialization; an overlay missing it raises AttributeError on the first
# upload, and the probe it skips is what stops a freed table name from
# inheriting its predecessor's cached authorization.
#
# 7 -> 8 (fix(#1546)): TWO CatalogPort changes, one bump. A required
# ``resolve_embedding_config`` method — semantic search filters stored
# embeddings on the configuration that produced them, and ``modules/catalog/``
# may not import ``app.processing.*``, so the answer crosses the port.
# Called on every hybrid search; an overlay missing it raises AttributeError
# on the first vector-arm query. And a widened ``generate_embedding``,
# taking a keyword-only ``pinned`` triple (model, dimensions, endpoint) —
# without it, the query vector can come from a different configuration than
# the rows it's ranked against within one request. An overlay on the old
# two-argument signature raises TypeError on the first semantic search.
#
# 8 -> 9 (fix(#1580)): THREE CatalogPort shape changes on the related-items
# path, one bump. ``get_record_embedding`` now returns ``(embedding,
# model_name, config_fingerprint)`` instead of a bare vector, since
# related-items compares two STORED rows and a list of floats can't say
# which model/endpoint produced it; an overlay returning a bare list raises
# when unpacked by ``service_relationships._compute_neighbor_distances``.
# ``get_embedding_distances`` gains required keyword-only ``model_name`` and
# ``config_fingerprint`` — required, not optional, so an overlay can't
# silently keep computing a similarity percentage in the wrong space.
# ``get_nearest_record_ids`` widens to take the caller's already-read anchor
# as a required keyword instead of reading its own, closing a READ COMMITTED
# race where two reads of the same record could anchor ranking and scoring
# on different rows.
#
# These three briefly rode INTO 7 -> 8 on the reasoning that #1546 and
# #1580 shipped in one release with no core release between them. That was
# wrong: the constant pins the contract at a COMMIT, not a release — main
# was a v8 contract from the moment #1546 merged, so an overlay declared
# against that commit boots cleanly against post-#1580 core and then hits
# AttributeError/TypeError on the first related-items request. Silent skew
# is exactly what this check exists to refuse.
#
# 9 -> 10 (fix(#2043)): CatalogPort gained a required
# ``ingest_budget_exceeded_error_class`` method — the re-upload preview lives
# in ``modules/catalog/`` and may not import ``app.processing.*``, so the one
# error class whose message it must pass through verbatim crosses the port.
# Called on every re-upload preview import of the module; an overlay missing
# it raises AttributeError at import time, not on first use.
EXTENSION_API_VERSION: int = 10


def check_extension_api_version(name: str, declared_version: int | None) -> None:
    """Raise ``RuntimeError`` if ``declared_version`` is not compatible with core.

    Called by ``load_extensions()`` BEFORE invoking each overlay's
    ``register_extensions`` callback. A version mismatch is a hard error
    that escapes the broad-except in the loader — the operator must fix
    the overlay or pin core to a compatible release before it can boot.

    ``declared_version=None`` (the overlay doesn't declare
    ``EXTENSION_API_VERSION``) is treated as legacy/version-0 and is
    **allowed to load** with a WARNING, not a hard failure — deliberate,
    since the enterprise overlay predates this constant and hard-failing on
    undeclared would brick every already-released overlay on a core
    upgrade. Only a concrete, mismatched integer raises.
    """
    if declared_version is None:
        logger.warning(
            "Overlay '%s' does not declare EXTENSION_API_VERSION; treating as "
            "legacy/version-0 and loading. Add `EXTENSION_API_VERSION = %d` to "
            "the overlay's register_extensions module to opt into skew detection. "
            "Core EXTENSION_API_VERSION=%d.",
            name,
            EXTENSION_API_VERSION,
            EXTENSION_API_VERSION,
        )
        return
    if declared_version != EXTENSION_API_VERSION:
        raise RuntimeError(
            f"Overlay '{name}' declares EXTENSION_API_VERSION={declared_version} "
            f"but core requires EXTENSION_API_VERSION={EXTENSION_API_VERSION}. "
            f"Update the overlay to match the core version or pin core to a compatible release."
        )
