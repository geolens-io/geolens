"""Dataset origin vocabulary: classification, pointer, and typed payload.

feat(#1218): one home for three things that must agree across the catalog
domain, the ingest tasks, and the API response boundary (ADR-002).

- ``classify_origin`` is the derivation ADR-002 Decision 2 deliberately keeps
  *derived*: origin is a pure function of ``source_format`` and
  ``record_type``, so no third column can disagree with the two it comes
  from. It moves server-side here so the CLI, MCP server, and SDKs stop
  needing a second implementation of the rule (the frontend's
  ``datasetOrigin()`` in ``OriginBadge.tsx`` becomes a consumer of the
  computed ``origin`` response field).
- ``build_origin_ref`` is the per-kind key allowlist that is the ONLY door
  into ``datasets.origin_ref``. Two ADR-002 guarantees are structural here
  rather than conventional: invariant 4 (the source binding holds no
  plaintext secret) holds because a key the kind does not declare raises, so
  ``token``/``password``/``authorization`` cannot land even by accident; and
  gate 2 (no external PostGIS federation in v1) holds because ``postgis``
  accepts ``table_name`` and nothing else — no host, port, DSN, or
  credential. Widening a JSON blob at a later PR's convenience is therefore
  not enough to add federation; it needs a new kind here.
- ``project_unknown`` is the NULL-means-unknown projection. NULL is the only
  stored spelling of "never determined" (the CHECK sets exclude ``unknown``),
  and the API renders it as the string at the boundary.

This lives under ``platform/`` rather than in the datasets domain because
both ``app.modules.catalog`` and ``app.processing.ingest`` write origins, and
processing/ may not import catalog (``test_no_processing_imports_catalog``).
It imports nothing from either side: the write helper is duck-typed on the
Dataset ORM instance. The one import is ``app.core``, the layer every other
layer may import.
"""

from __future__ import annotations

from typing import Any

from app.core.record_types import RASTER_FAMILY_RECORD_TYPES

# Formats whose rows were pulled from a remote OGC/Esri service. Mirrors
# SERVICE_FORMATS in frontend/src/components/dataset/OriginBadge.tsx.
SERVICE_SOURCE_FORMATS: frozenset[str] = frozenset(
    {"wfs", "arcgis_featureserver", "ogcapi_features"}
)

# Record types with no dataset origin of their own: a collection has no
# dataset row at all, and a VRT is composed from other datasets rather than
# fetched from anywhere. Both classify as None so the type badge speaks alone.
_ORIGINLESS_RECORD_TYPES: frozenset[str] = frozenset({"collection", "vrt_dataset"})

# fix(#1325): this is the dataset's ORIGIN — how its data entered the
# catalog. It is DERIVED, not stored: classify_origin() recomputes it from
# the dataset's CURRENT source_format/record_type every time a response is
# built (datasets/domain/helpers.py:192). It changes only when a mutation
# crosses one of classify_origin()'s category boundaries, e.g. a successful
# raster replace reclassifying 'stac' to 'upload' by setting
# source_format='geotiff'; a same-category reupload such as GeoJSON to CSV
# (both classify to 'upload', per _apply_reupload_swap in tasks_common.py)
# leaves it unchanged. It is a DIFFERENT vocabulary from
# DatasetRefreshRun.origin_kind, the CHECK constraint in
# platform/refresh/models.py: that column is the run's
# execution DOOR, written once by create_pending_run at commit time and
# never updated afterward (platform/refresh/service.py has no other writer)
# — the immutable side of a comparison whose other side, the dataset's
# origin, is not. Do NOT read the ledger's origin_kind as "this dataset's
# origin, restated at the run level": a run's door and its dataset's CURRENT
# origin can visibly disagree, because the door was fixed once, at commit
# time, while the origin keeps answering for whatever source_format says
# right now. Concretely: a STAC-imported raster (dataset.origin == 'stac')
# that gets replaced has its run row stamped origin_kind='upload' at commit
# time (router_reupload.py), while the dataset's origin only moves to
# 'upload' once a SUCCESSFUL swap rebinds source_format to 'geotiff'
# (tasks_raster_swap.py:_write_swapped_fields). While that run is pending,
# and permanently if it fails, the run still says 'upload' and the dataset
# still says 'stac'. 'created' is here but has no ledger counterpart,
# because a dataset drawn in the app has nothing to refresh from. The
# ledger's 'raster' has no ORIGIN_KINDS counterpart at all: it is RESERVED
# for a future, distinct raster-replace door label; today every
# raster-replace run's door is 'upload', independent of the dataset's own
# origin.
ORIGIN_KINDS: frozenset[str] = frozenset(
    {"upload", "postgis", "service", "stac", "created"}
)

# The response-boundary spelling of "never determined". Deliberately absent
# from chk_datasets_source_health / chk_datasets_schema_drift_status: with
# both NULL and 'unknown' storable, every query would have to handle two
# spellings of one state forever.
UNKNOWN: str = "unknown"

# Stored value sets, matching the two CHECK constraints on catalog.datasets.
SOURCE_HEALTH_VALUES: tuple[str, ...] = ("healthy", "missing", "inaccessible")
SCHEMA_DRIFT_STATUS_VALUES: tuple[str, ...] = ("none", "drifted")

# Keys each origin kind may carry in origin_ref, beside the `kind`
# discriminator itself. Adding a key here widens what can be persisted about
# an origin, so treat it as a schema change.
ORIGIN_REF_KEYS: dict[str, frozenset[str]] = {
    # `layer_id` is the SERVICE-NATIVE layer identifier, and which field that
    # is depends on service_type (fix #1218 review r3). `build_gdal_source` in
    # catalog/sources/preview.py is the authority:
    #
    #   arcgis_featureserver -> the numeric layer id. Required; the layer NAME
    #                           is ignored, the id becomes a URL path segment.
    #   wfs                  -> the typename, passed to GDAL as the layer name.
    #                           layer_id is ignored.
    #   ogcapi_features      -> the collection id, same handling as wfs.
    #
    # Exactly one of the two identifies the layer for a given service, so they
    # cannot disagree, and one key is enough for a refresh to re-address the
    # layer. Do NOT add a second key for the name: that would create two fields
    # with overlapping meaning and leave a refresh to guess which one applies.
    #
    # THE INVARIANT (fix #1218 review r4): `url` is the service BASE for every
    # service_type, `layer_id` is the service-native layer identifier, and the
    # url NEVER embeds the layer. A refresh composes the two per service; it
    # must never have to strip a layer back out of the url. Note this is why
    # `url` is not the same value as `datasets.origin_uri`, which deliberately
    # keeps the enriched form ingest composed, as provenance.
    #
    # `auth_required` (fix #1746) records that the last SUCCESSFUL pull of this
    # origin needed a service token. It is `True` or absent, never `False`, so
    # an unauthenticated pull stores the exact ref shape it stored before the
    # key existed and no backfill is owed — the same absent-means-no convention
    # `managed` uses on the postgis kind. The worker writes it at the service
    # swap, from the credential it actually used; a request door only knows a
    # token was offered. Never the token itself: this is a boolean.
    "service": frozenset({"service_type", "url", "layer_id", "auth_required"}),
    # `asset_href` is additive to ADR-002's declared stac shape, and the two
    # href keys are NOT interchangeable: `asset_href` is the COG the tiler
    # reads, `item_href` is the STAC item document that publishes it. A 200 on
    # one says nothing about the other, which is exactly why the health probe
    # (#1222) wants both. `item_href` was reserved-but-unwritten until #1222
    # taught STAC search to surface the item's rel=self link and the import
    # request to echo it back; it stays absent for catalogs that publish no
    # self link, and for datasets imported before that landed.
    # `item_id` is the item's identity as the CATALOG states it, and it is
    # here rather than read from `datasets.source_filename` — which holds the
    # same string — because that field is in the metadata PATCH's map. A
    # user-editable value that decides which remote item a dataset gets
    # re-pointed at is a rebinding primitive, not a pointer (fix #1266 review
    # round 9). With it stored, a refresh can refuse a document that answers
    # for a different item even when the item's URL states no identity of its
    # own; without it, only catalogs using the `/collections/{c}/items/{id}`
    # layout can be checked at all.
    "stac": frozenset(
        {"item_href", "item_id", "asset_href", "collection_id", "asset_key"}
    ),
    "upload": frozenset({"filename", "file_hash"}),
    # Gate 2: GeoLens-internal table only. No host/port/DSN/credential key.
    #
    # fix(#1452): `managed` is the one bit that separates the two callers of
    # register_existing_table. Both produce a postgis origin, and until this
    # key existed nothing told them apart: an operator registering a table
    # they built, and the analysis materialize path registering a table
    # GeoLens just CTAS'd. Delete has to tell them apart, because dropping
    # the first destroys data GeoLens never created a copy of. Absent means
    # NOT managed, which is what makes the back catalog — every dataset
    # registered before this key existed — fall on the side that preserves
    # the operator's table. That default costs a leaked table for analysis
    # outputs registered before this shipped; the other default costs
    # irreversible loss of data GeoLens does not own, so the asymmetry
    # decides it. It is an ownership fact about the SAME table the pointer
    # names, not a second pointer, so gate 2 is untouched.
    "postgis": frozenset({"table_name", "managed"}),
    # A dataset drawn in the app came from nowhere; it carries no payload.
    "created": frozenset(),
}


def classify_origin(
    source_format: str | None, record_type: str | None = None
) -> str | None:
    """How the data entered the catalog, derived from the two stored columns.

    Registering an existing PostGIS table stores no ``source_format`` (see
    ``register_existing_table``), so a null format means "referenced in
    place" rather than "unknown".
    """
    resolved_type = record_type or "vector_dataset"
    if resolved_type in _ORIGINLESS_RECORD_TYPES:
        return None
    if not source_format:
        return "postgis"
    if source_format == "created":
        return "created"
    if source_format == "stac":
        return "stac"
    if source_format in SERVICE_SOURCE_FORMATS:
        return "service"
    return "upload"


def set_postgis_origin(
    dataset: Any, table_name: str, *, schema: str, managed: bool = False
) -> None:
    """Stamp a registered PostGIS table's origin.

    Separate from the generic writer because the pointer and the ref's
    ``table_name`` are two spellings of one fact and have to agree. Composing
    them at the call site is how they drift, so the qualified name is built
    once here and the URI is derived from it.

    ``schema`` is passed in rather than derived, and specifically NOT derived
    from ``dataset.tenant_id`` (fix #1218 review round 2). In multi-tenant
    mode the INSERT sends ``tenant_id`` as NULL and the
    ``trg_stamp_current_tenant_on_insert`` trigger fills it from the
    ``app.current_tenant`` GUC, so the real value exists only in the database
    and the ORM attribute stays None — every multi-tenant registration would
    have been pointed at ``data.<table>`` for a table living in
    ``data_t_<tenant>``. Callers pass the schema they actually created,
    granted, and read the table in, which makes the pointer agree with
    physical placement by construction rather than by a parallel derivation.

    ``managed`` says GeoLens created the table it is about to register and may
    drop it again (fix #1452). It is passed as ``True``/``None`` rather than
    ``True``/``False`` so an unmanaged registration stores the exact ref shape
    it stored before the key existed — ``build_origin_ref`` omits ``None`` —
    and every reader goes through :func:`geolens_owns_table`, which reads an
    absent key and a stored ``false`` the same way.
    """
    qualified = f"{schema}.{table_name}"
    set_dataset_origin(
        dataset,
        "postgis",
        uri=f"postgis://{qualified}",
        table_name=qualified,
        managed=True if managed else None,
    )


def geolens_owns_table(
    source_format: str | None,
    record_type: str | None,
    origin_ref: Any,
) -> bool:
    """Whether GeoLens created this dataset's physical table and may drop it.

    fix(#1452): the question ``delete_dataset`` has to answer before it issues
    a DROP. Every origin but ``postgis`` describes data GeoLens materialized
    into a table of its own making — an upload run through ogr2ogr, a service
    or STAC pull, a layer drawn in the app — so the table is GeoLens's to
    reclaim. ``postgis`` is the registered-in-place origin, where registration
    copies no data and the catalog row is a reference to a table the operator
    built; dropping that destroys the original, not a managed copy.

    The one exception is the analysis materialize path, which CTAS's its own
    output table and then registers it through the same helper an operator
    uses. It stamps ``managed`` on the ref, and that is the only thing
    separating the two — see ``ORIGIN_REF_KEYS['postgis']`` for why an absent
    key resolves to "not ours".

    Also the condition for retiring the name in ``catalog.retired_table_names``
    (GH-1443), because the two questions have one answer: a name is freed only
    when the relation behind it is gone. A detached table still exists and
    still holds the operator's rows, so retiring its name would free nothing
    and would permanently refuse the re-registration that is the whole point
    of leaving the table alone.

    ``origin_ref`` is typed ``Any`` on purpose: the column is JSONB and the ORM
    hands back whatever is stored, which is not necessarily what
    ``build_origin_ref`` would have written. The caller is one line above a
    DROP, so the shape is checked rather than assumed.
    """
    # Registration is the only writer of a postgis origin and it only ever
    # creates vector datasets, so a raster or VRT is GeoLens's by construction.
    # Stated structurally rather than left to classify_origin, which would
    # answer "postgis" for a raster whose source_format happened to be NULL and
    # silently stop retiring its name (GH-1443). Every raster path stamps a
    # format today; this makes that a fact rather than a dependency.
    if record_type in RASTER_FAMILY_RECORD_TYPES:
        return True
    if classify_origin(source_format, record_type) != "postgis":
        return True
    if not isinstance(origin_ref, dict):
        return False
    # `is True`, not truthiness: a stored "yes" or 1 is not a claim this
    # function is willing to drop a table on.
    return origin_ref.get("managed") is True


def service_auth_required(origin_ref: Any) -> bool:
    """Whether the last successful pull of this service origin used a token.

    fix(#1746): `is True`, not truthiness, for the same reason
    ``geolens_owns_table`` spells it that way — this decides whether a request
    is refused, and a stored 1 or "yes" is not a claim worth refusing on.
    """
    if not isinstance(origin_ref, dict):
        return False
    return origin_ref.get("auth_required") is True


def service_layer_identity(
    service_type: str, *, layer_id: Any, layer_name: str | None
) -> str | None:
    """The service-native layer identifier for a service ``origin_ref``.

    Which field addresses a layer depends on the service, and
    ``build_gdal_source`` in ``catalog/sources/preview.py`` is the authority:
    its ArcGIS branch requires the numeric ``layer_id`` and discards the layer
    name, while its WFS and OGC API branches pass the layer NAME to GDAL and
    never read ``layer_id``. Exactly one applies per service, so they cannot
    disagree and one stored key is enough.

    Lives here rather than at the two ingest call sites so both spell the rule
    the same way and a change has one place to happen (fix #1218 review r3).
    """
    if service_type == "arcgis_featureserver":
        return None if layer_id is None else str(layer_id)
    return layer_name


def build_origin_ref(kind: str, **fields: Any) -> dict[str, Any] | None:
    """Validated ``origin_ref`` payload for one origin kind.

    Raises on any key the kind does not declare rather than dropping it: a
    silent drop would make a mis-keyed write indistinguishable from a
    correct one, and this allowlist is the enforcement point for ADR-002
    invariant 4 and gate 2. ``None``-valued fields are omitted, so an absent
    file hash simply leaves the key out.

    Returns ``None`` for a kind with no payload (``created``).
    """
    try:
        allowed = ORIGIN_REF_KEYS[kind]
    except KeyError:
        raise ValueError(
            f"unknown origin kind {kind!r}; expected one of {sorted(ORIGIN_KINDS)}"
        ) from None

    rejected = sorted(set(fields) - allowed)
    if rejected:
        raise ValueError(
            f"origin_ref[{kind}] rejects key(s) {rejected}; "
            f"allowed keys are {sorted(allowed)}"
        )

    payload = {
        key: fields[key] for key in sorted(allowed) if fields.get(key) is not None
    }
    if not payload and not allowed:
        return None
    return {"kind": kind, **payload}


def set_dataset_origin(
    dataset: Any, kind: str, *, uri: str | None = None, **ref_fields: Any
) -> None:
    """Write the system-managed origin pointer onto a Dataset ORM instance.

    The only supported way to populate ``origin_uri``/``origin_ref``. Neither
    column appears in ``_DATASET_FIELD_MAP``, so nothing reaches them through
    the metadata PATCH; ingest and refresh paths come through here.
    """
    if kind not in ORIGIN_KINDS:
        raise ValueError(
            f"unknown origin kind {kind!r}; expected one of {sorted(ORIGIN_KINDS)}"
        )
    # fix(#1271 review): every caller of this function is a successful-ingest
    # commit, so the binding write is the moment the stored probe verdict
    # stops describing anything real. Either the binding now names a
    # DIFFERENT origin (a service marked missing and reuploaded from a file
    # would otherwise serve missing/not_found forever, since uploads 409 the
    # probe), or it re-stamps the SAME origin that the swap just exercised —
    # in which case a pre-swap failure verdict is stale the other way round:
    # the origin demonstrably answered. NULL is the honest value either way
    # (the API projects it as unknown); writing "healthy" here would be a
    # second, weaker classifier beside the probe's. Refresh paths that
    # contacted the origin re-stamp last_checked_at in their own projection
    # after this call.
    dataset.source_health = None
    dataset.source_health_detail = None
    dataset.last_checked_at = None
    dataset.origin_uri = uri
    dataset.origin_ref = build_origin_ref(kind, **ref_fields)


def project_unknown(value: str | None) -> str:
    """Render a never-determined source-state column at the API boundary."""
    return UNKNOWN if value is None else value
