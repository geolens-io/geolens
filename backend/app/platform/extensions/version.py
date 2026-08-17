"""Extension API version contract for GeoLens overlay compatibility (OCG-04).

``EXTENSION_API_VERSION`` is an **integer** that increments whenever a Protocol
signature or registry contract changes in a way that requires overlay updates.

Bump convention
---------------
Bump this constant (and update overlay packages before re-releasing core) when:

- A required method is added to or removed from any Protocol in ``protocols.py``.
- A registry key is renamed or its expected type changes.
- The ``register_extensions(registry)`` calling convention changes.
- A single-slot vs. additive-slot classification changes for an existing key.

**Do NOT bump** for:
- New optional methods (Protocol evolution with default no-ops).
- New registry keys that overlays may optionally populate.
- Internal implementation changes with no contract impact.

Overlay declaration
-------------------
Each overlay **should** declare (recommended — opts the overlay into skew
detection)::

    from app.platform.extensions.version import EXTENSION_API_VERSION

as a module-level attribute in its ``register_extensions`` module (e.g. the
callable returned by the ``geolens.extensions`` entry point). The loader reads
this attribute via ``getattr(loader, "EXTENSION_API_VERSION", None)`` and calls
``check_extension_api_version()`` before invoking the overlay. An overlay that
does not declare a version is treated as legacy/version-0 and loads with a
WARNING (backward compatibility — see ``check_extension_api_version``); only a
declared-but-mismatched version is a hard failure.

References: OCG-04
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: v2 adds required ConnectorExtension discovery/dispatch methods and makes the
#: existing ``connectors`` registry key conflict-guarded as a single slot.
# 2 -> 3 (feat(#683)): ProcessingPort.run_analysis_preview gained a
# ``mask_dataset`` keyword so chat can clip a layer by another layer. It is
# optional with a default, so an overlay that never implements the method is
# unaffected — but one that DOES implement it must accept the keyword, which
# is a signature change to a Protocol method and therefore a bump. The caller
# also omits the keyword entirely when it is None, so a legacy overlay that
# declares no version keeps working for buffer and centroid.
# 3 -> 4 (feat(#1068)): PermissionExtension gained a required
# ``record_audience`` method — the audience-shaped reading of the same policy
# ``filter_visible`` and ``can_access_dataset`` already express per user. An
# overlay that replaces the ``permission`` slot must implement it, and must
# implement it whenever it changes either of those two: core cannot tell a
# missing answer from a wrong one, so an authority that overrides reads while
# inheriting the community audience is treated as unable to answer and gets the
# conservative refusal (see find_maps_broken_by_dataset_visibility).
# 4 -> 5 (fix(#1314)): ProcessingPort gained a required
# ``reconcile_distributions`` method. An overlay that replaces the
# ``processing_port`` slot must implement it: the registered-PostGIS refresh
# and the reupload swap both call it whenever the modality of the dataset they
# just measured differs from the stored one, so without this bump a
# version-4 overlay loads cleanly and then raises AttributeError inside the
# write transaction of the first refresh that matters. Skew that the loader
# refuses at boot is the whole point of this constant.
#
# This bump carries the required-method addition ONLY. The deprecated
# import-compatibility aliases in protocols.py and defaults.py that their own
# comments defer "until the next EXTENSION_API_VERSION bump" are NOT removed
# here — that removal is a separate change with its own review, and a bump
# forced by an unrelated Protocol addition is not the occasion for it.
#
# 5 -> 6 (refactor(stac)): CatalogPort gained a required
# ``fetch_raster_meta_bulk_without_vrt`` method — the raster-meta read narrowed
# to what a STAC Item may carry, now that the STAC router reads through the
# port instead of importing processing ORM. Every item and item-page response
# calls it, including an empty page, so an overlay that replaces the
# ``catalog_port`` slot without it would load cleanly at version 5 and then
# raise AttributeError on the first STAC request. The additive shape is not an
# exemption here: the "do NOT bump for new optional methods" carve-out above
# means methods with a default no-op, and a Protocol method a structural
# implementer must supply is required by definition.
#
# 6 -> 7 (fix(GH-1443)): ProcessingPort gained a required
# ``get_retired_table_name_orm_class`` method. ``generate_table_name`` lives in
# processing/ and so cannot import the catalog model it now has to probe; the
# accessor is how it reaches one. Every ingest, analysis output, and layer
# materialization calls that function, so an overlay replacing the
# ``processing_port`` slot without the accessor would load cleanly at version 6
# and then raise AttributeError on the first upload — and the probe it skips is
# the one keeping a freed table name from being handed to a successor that
# inherits its predecessor's cached authorization. Same reasoning as 4 -> 5 and
# 5 -> 6: a Protocol method a structural implementer must supply is required,
# whatever else the addition is shaped like.
#
# 7 -> 8 (fix(#1546), then fix(#1580)): FOUR CatalogPort changes, one bump.
#
# The first two land with #1546 and the second two with #1580, in the same
# release with no core release between them. An overlay author sees one contract
# change, so they get one number: a second bump inside a release is a second pin
# to maintain for a migration nobody performs separately.
#
# A required ``resolve_embedding_config`` method. Stored embeddings now carry
# the identity of the configuration that produced them, and semantic search
# filters on it, so the search path has to be able to ask what the live
# configuration is; ``modules/catalog/`` may not import ``app.processing.*``,
# which is why the answer crosses the port. Every hybrid search calls it, so an
# overlay replacing the ``catalog_port`` slot without it would load cleanly at
# version 7 and then raise AttributeError on the first query long enough to
# reach the vector arm. Same reasoning as 5 -> 6: a Protocol method a
# structural implementer must supply is required, whatever else it is shaped
# like.
#
# And a widened ``generate_embedding``, which takes a keyword-only ``pinned``
# triple (model, dimensions, endpoint). Filtering rows by a configuration while
# letting the provider re-resolve its own leaves a window inside ONE request
# where the query vector comes from a different configuration than the rows it
# is ranked against, which is the whole defect #1546 exists to close. An
# overlay that implements the old two-argument signature raises TypeError on
# the first semantic search, so this is as required as the addition above.
# Riding the same bump because both land in the same change; an overlay
# updating to 8 has to do both.
#
# Then fix(#1580), the related-items path, on the same number. Related items
# compared one record's stored vector against every other record's across model
# and configuration spaces; scoping that comparison needs the anchor row's
# identity to reach two more readers.
#
# ``get_record_embedding`` returns ``(embedding, model_name,
# config_fingerprint)`` instead of a bare vector. Both sides of that comparison
# are STORED rows, so the caller has to name the vector space the anchor is in
# and hold every later read to it, and a list of floats cannot say which model
# or endpoint produced it. An overlay still returning a bare list is unpacked
# into three names by ``service_relationships._load_self_record_and_embedding``
# and raises on the first related-items request.
#
# ``get_embedding_distances`` gains required keyword-only ``model_name`` and
# ``config_fingerprint``. Required rather than optional on purpose: defaulting
# them to "no filter" would let an overlay keep the defect silently, and the
# defect is a similarity percentage computed in the wrong space. An overlay
# implementing the old signature raises TypeError on the same request.
#
# All four are the same test every bump before this one applied: a Protocol
# method a structural implementer must supply, in a shape the core caller
# depends on. An overlay updating to 8 has to do all four.
EXTENSION_API_VERSION: int = 8


def check_extension_api_version(name: str, declared_version: int | None) -> None:
    """Raise ``RuntimeError`` if ``declared_version`` is not compatible with core.

    Called by ``load_extensions()`` BEFORE invoking each overlay's
    ``register_extensions`` callback. A version mismatch is a hard error that
    escapes the broad-except in the loader — the operator must fix the overlay
    or pin the core to a compatible release before the service can boot.

    Parameters
    ----------
    name:
        The entry-point name of the overlay (used in the error message).
    declared_version:
        The value of ``EXTENSION_API_VERSION`` read from the overlay's loader
        callable. ``None`` means the overlay does not declare a version
        (legacy overlay — version-0 convention).

    Backward compatibility
    ----------------------
    An overlay that does **not** declare ``EXTENSION_API_VERSION`` (``None``) is
    treated as a legacy/version-0 overlay and is **allowed to load** with a
    WARNING — NOT a hard failure. This is deliberate open-core hygiene: the
    enterprise overlay is a separately-distributed package that predates this
    constant, so hard-failing on undeclared would brick every already-released
    overlay the moment a customer upgrades core. The skew protection OCG-04
    targets is the *declared-but-mismatched* case, which still raises. A future
    core MAY tighten this to require declaration once all shipped overlays
    declare a version.

    Raises
    ------
    RuntimeError
        Only when ``declared_version`` is a concrete integer that does not equal
        ``EXTENSION_API_VERSION`` (genuine version skew). Undeclared (``None``)
        does not raise.
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
