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
Dataset ORM instance.
"""

from __future__ import annotations

from typing import Any

# Formats whose rows were pulled from a remote OGC/Esri service. Mirrors
# SERVICE_FORMATS in frontend/src/components/dataset/OriginBadge.tsx.
SERVICE_SOURCE_FORMATS: frozenset[str] = frozenset(
    {"wfs", "arcgis_featureserver", "ogcapi_features"}
)

# Record types with no dataset origin of their own: a collection has no
# dataset row at all, and a VRT is composed from other datasets rather than
# fetched from anywhere. Both classify as None so the type badge speaks alone.
_ORIGINLESS_RECORD_TYPES: frozenset[str] = frozenset({"collection", "vrt_dataset"})

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
    "service": frozenset({"service_type", "url", "layer_id"}),
    # `asset_href` is additive to ADR-002's declared stac shape. The STAC
    # import request carries the item id, the collection id, and the chosen
    # data-asset href — never the item's own href — so writing that asset URL
    # into a key named `item_href` would be a lie in the payload. The key is
    # reserved and stays unwritten until the import request carries it
    # (#1222 owns the STAC health probe that will want it).
    "stac": frozenset({"item_href", "asset_href", "collection_id", "asset_key"}),
    "upload": frozenset({"filename", "file_hash"}),
    # Gate 2: GeoLens-internal table only. No host/port/DSN/credential key.
    "postgis": frozenset({"table_name"}),
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


def set_postgis_origin(dataset: Any, table_name: str, *, schema: str) -> None:
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
    """
    qualified = f"{schema}.{table_name}"
    set_dataset_origin(
        dataset, "postgis", uri=f"postgis://{qualified}", table_name=qualified
    )


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
    dataset.origin_uri = uri
    dataset.origin_ref = build_origin_ref(kind, **ref_fields)


def project_unknown(value: str | None) -> str:
    """Render a never-determined source-state column at the API boundary."""
    return UNKNOWN if value is None else value
