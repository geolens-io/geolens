"""Dataset origin vocabulary: classification, pointer, and typed payload.

One home for three things that must agree across the catalog
domain, the ingest tasks, and the API response boundary.

- ``classify_origin`` is the derivation ADR-002 Decision 2 keeps *derived*:
  origin is a pure function of ``source_format``/``record_type``, so no
  third column can disagree. Server-side so the CLI, MCP server, SDKs and
  frontend read the ``origin`` response field instead of reimplementing it.
- ``build_origin_ref`` is the per-kind key allowlist, the ONLY door into
  ``datasets.origin_ref``. Enforces ADR-002 invariant 4 (no plaintext
  secret — an undeclared key like ``token``/``password``/``authorization``
  raises) and gate 2 (no external PostGIS federation — ``postgis`` accepts
  only ``table_name``). Widening the JSON blob alone can't add federation;
  it needs a new kind here.
- ``project_unknown`` is the NULL-means-unknown projection: NULL is the
  only stored spelling of "never determined" (the CHECK sets exclude
  ``unknown``), rendered as that string at the API boundary.

Lives under ``platform/``, not the datasets domain: both
``app.modules.catalog`` and ``app.processing.ingest`` write origins, and
processing/ may not import catalog (``test_no_processing_imports_catalog``).
Imports nothing from either side — the write helper is duck-typed on the
Dataset ORM instance.
"""

from __future__ import annotations

from typing import Any, Literal

from app.core.record_types import RASTER_FAMILY_RECORD_TYPES
from app.platform.portal_link import (
    LOSS_LINK_UNSUPPORTED,
    LOSS_PORTAL_URL_DOMAIN_MISMATCH,
    resolve_portal_link,
    same_registrable_domain,
)

# Formats whose rows were pulled from a remote OGC/Esri service. Mirrors
# SERVICE_FORMATS in frontend/src/components/dataset/OriginBadge.tsx.
SERVICE_SOURCE_FORMATS: frozenset[str] = frozenset(
    {"wfs", "arcgis_featureserver", "ogcapi_features"}
)

# Record types with no dataset origin of their own: a collection has no
# dataset row at all, and a VRT is composed from other datasets rather than
# fetched from anywhere. Both classify as None so the type badge speaks alone.
_ORIGINLESS_RECORD_TYPES: frozenset[str] = frozenset({"collection", "vrt_dataset"})

# The dataset's ORIGIN: how its data entered the catalog. DERIVED, not
# stored: classify_origin() recomputes it from the CURRENT
# source_format/record_type on every response, so it only changes when a
# mutation crosses a category boundary (e.g. a raster replace reclassifying
# 'stac' to 'upload').
#
# DIFFERENT vocabulary from DatasetRefreshRun.origin_kind
# (platform/refresh/models.py), the run's execution DOOR, written once at
# commit and never updated: a STAC-imported raster being replaced gets
# origin_kind='upload' at commit, while dataset.origin stays 'stac' until a
# SUCCESSFUL swap rebinds source_format. 'created' has no ledger
# counterpart; the ledger's 'raster' is RESERVED and unused, since every
# raster-replace door is 'upload'.
ORIGIN_KINDS: frozenset[str] = frozenset(
    {"upload", "postgis", "service", "stac", "created"}
)

# The same vocabulary as a request-model annotation, so a door that takes an
# origin kind as INPUT rejects an unknown one at the schema boundary and
# publishes the closed set in OpenAPI. `test_reupload_expected_origin_1768.py`
# asserts the two agree.
OriginKind = Literal["upload", "postgis", "service", "stac", "created"]

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
    # `layer_id` is the SERVICE-NATIVE layer identifier (see
    # `service_layer_identity`). Exactly one applies per service, so a
    # refresh needs only that one key.
    #
    # THE INVARIANT: `url` is the service BASE for every service_type and
    # NEVER embeds the layer; `layer_id` is the layer. A refresh composes the
    # two and never strips a layer back out of `url`. This is why `url`
    # differs from `datasets.origin_uri`, which keeps ingest's enriched form
    # as provenance.
    #
    # `auth_required`: the last SUCCESSFUL pull used a service token, NOT
    # "the origin demands one". The worker writes it from the credential it
    # actually used, so a public service imported while the user held a token
    # is marked too; the refresh door treats the key as a gate (one token-less
    # probe before refusing), not a verdict. `True` or absent, never `False`,
    # like `managed` on the postgis kind. A later token-less success clears
    # it. Never the token itself.
    #
    # `item_id`/`portal_url` name the portal item the data was built from
    # (see `resolve_portal_link`, the only validated source). The `upload`
    # kind carries them too, and `set_dataset_origin` keeps them across every
    # restamp of either kind.
    "service": frozenset(
        {"service_type", "url", "layer_id", "auth_required", "item_id", "portal_url"}
    ),
    # `asset_href` (additive to ADR-002's stac shape) is the COG the tiler
    # reads; `item_href` is the STAC item document. They are not
    # interchangeable, so the health probe wants both. `item_href` is absent
    # for catalogs with no self link and for older imports.
    # `item_id` is the item's identity per the CATALOG, stored here rather
    # than read from `datasets.source_filename` (the same string) because
    # that field is user-editable through the metadata PATCH. With it stored,
    # a refresh can refuse a document answering for a different item even
    # when the item's URL states no identity of its own.
    # `auth_required` means what it means on the service kind.
    #
    # `url` is the catalog root the CALLER submitted at import, and it is the
    # only value here the catalog itself never chose. A credentialed refresh
    # anchors on it, so a document that names another host cannot name where
    # the credential goes. Absent on bindings imported before it existed.
    "stac": frozenset(
        {
            "url",
            "item_href",
            "item_id",
            "asset_href",
            "collection_id",
            "asset_key",
            "auth_required",
        }
    ),
    "upload": frozenset({"filename", "file_hash", "item_id", "portal_url"}),
    # Gate 2: GeoLens-internal table only. No host/port/DSN/credential key.
    #
    # `managed` is the one bit separating the two callers of
    # `register_existing_table`: an operator registering their own table, vs.
    # the analysis materialize path registering a table GeoLens just CTAS'd.
    # Delete must tell them apart — dropping the first destroys data GeoLens
    # never copied. Absent means NOT managed, so datasets without the key
    # keep the operator's table: a leaked table is recoverable, dropping data
    # GeoLens doesn't own is not. An ownership fact about the SAME table, not
    # a second pointer, so gate 2 is untouched.
    "postgis": frozenset({"table_name", "managed"}),
    # A dataset drawn in the app came from nowhere; it carries no payload.
    "created": frozenset(),
}


PORTAL_LINK_KEYS: tuple[str, ...] = ("item_id", "portal_url")
_PORTAL_LINK_KINDS = frozenset({"service", "upload"})


def portal_link_fields(mapping: Any) -> dict[str, str]:
    """The portal link keys a mapping holds as strings (job metadata or a ref)."""
    if not isinstance(mapping, dict):
        return {}
    return {
        key: mapping[key]
        for key in PORTAL_LINK_KEYS
        if isinstance(mapping.get(key), str)
    }


def carried_portal_link(origin_ref: Any) -> dict[str, str]:
    """The portal link a stored ref holds, for a restamp to keep.

    Only a service or upload ref counts: a STAC ref's ``item_id`` is the
    catalog's item, not a portal item.
    """
    if (
        not isinstance(origin_ref, dict)
        or origin_ref.get("kind") not in _PORTAL_LINK_KINDS
    ):
        return {}
    return portal_link_fields(origin_ref)


def _carry_losses(
    old_ref: Any, carried: dict[str, str], kind: str, ref_fields: dict[str, Any]
) -> list[str]:
    """Why a carried link no longer fits the origin being stamped.

    A link is ArcGIS-only, and a service's portal shares its host's
    registrable domain, so a rebind to another host (or another vendor's
    service) no longer names the same item.
    """
    if not carried or kind != "service":
        return []
    service_type = ref_fields.get("service_type")
    if isinstance(service_type, str) and not service_type.startswith("arcgis"):
        return [LOSS_LINK_UNSUPPORTED]
    new_url = ref_fields.get("url")
    if not new_url:
        return []
    if "portal_url" in carried:
        return resolve_portal_link(None, carried["portal_url"], new_url).losses
    old_url = old_ref.get("url") if old_ref.get("kind") == "service" else None
    if old_url and not same_registrable_domain(old_url, new_url):
        return [LOSS_PORTAL_URL_DOMAIN_MISMATCH]
    return []


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
    ``table_name`` must agree, and composing them at the call site is how
    they drift — the qualified name is built once here.

    ``schema`` is passed in, not derived from ``dataset.tenant_id``: in
    multi-tenant mode the INSERT sends ``tenant_id`` as NULL and a trigger
    fills it from a GUC, so the ORM attribute stays None and deriving here
    would point every multi-tenant registration at the wrong schema.

    ``managed`` says GeoLens created this table and may drop it again.
    Passed as ``True``/``None``, not ``True``/``False``, so an unmanaged
    registration's ref carries no key (``build_origin_ref`` omits ``None``);
    every reader goes through :func:`geolens_owns_table`.
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

    The question ``delete_dataset`` answers before a DROP. Every
    origin but ``postgis`` is data GeoLens materialized into its own table
    (upload, service/STAC pull, a drawn layer). ``postgis`` is
    registered-in-place — registration copies no data, and the row
    references a table the operator built; dropping that destroys the
    original.

    Exception: the analysis materialize path CTAS's its own output and
    registers it through the same helper an operator uses, stamping
    ``managed`` — the only thing telling the two apart (see
    ``ORIGIN_REF_KEYS['postgis']`` for why an absent key means "not ours").

    Also the condition for retiring a name in
    ``catalog.retired_table_names``: a name frees only when the
    relation is gone. A detached table still holds the operator's rows, so
    retiring its name would permanently refuse re-registration.

    ``origin_ref`` is typed ``Any``: the column is JSONB and the ORM
    returns whatever is stored, not necessarily what ``build_origin_ref``
    would have written, so the shape is checked here rather than assumed.
    """
    # Registration is the only writer of a postgis origin, and it only
    # creates vector datasets, so a raster/VRT is GeoLens's by construction
    # — stated structurally rather than via classify_origin, which would
    # answer "postgis" for a raster with a NULL source_format and silently
    # stop retiring its name.
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
    """Whether the last successful pull of this origin used a credential.

    A token was USED, not demanded: no caller may read this as "the origin
    requires authentication" — the refresh door checks that separately.

    Reads the key on the STAC kind too, which stores it under
    the same name and the same rule.

    ``is True``, not truthiness, same reason as
    ``geolens_owns_table`` — this gates an outbound request/refusal, and a
    stored 1 or "yes" isn't a claim worth acting on.
    """
    if not isinstance(origin_ref, dict):
        return False
    return origin_ref.get("auth_required") is True


def service_layer_identity(
    service_type: str, *, layer_id: Any, layer_name: str | None
) -> str | None:
    """The service-native layer identifier for a service ``origin_ref``.

    Which field applies depends on the service; ``build_gdal_source``
    (``catalog/sources/preview.py``) is the authority: ArcGIS requires the
    numeric ``layer_id`` and discards the layer name, WFS/OGC API pass the
    layer NAME to GDAL and never read ``layer_id``. Exactly one applies per
    service.

    Lives here, not at the two ingest call sites, so both spell the rule the
    same way.
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
) -> list[str]:
    """Write the system-managed origin pointer onto a Dataset ORM instance.

    The only supported way to populate ``origin_uri``/``origin_ref``. Neither
    column appears in ``_DATASET_FIELD_MAP``, so nothing reaches them through
    the metadata PATCH; ingest and refresh paths come through here.

    Returns the loss codes of a portal link dropped instead of carried
    forward: a service restamp whose host no longer shares the link's domain
    loses ``item_id`` and ``portal_url`` together.
    """
    if kind not in ORIGIN_KINDS:
        raise ValueError(
            f"unknown origin kind {kind!r}; expected one of {sorted(ORIGIN_KINDS)}"
        )
    # Every caller here is a successful-ingest commit, so the stored probe
    # verdict no longer describes anything real: the binding names a
    # DIFFERENT origin, or re-stamps the SAME one a pre-swap failure verdict
    # is stale about. NULL (projected as unknown) is honest either way;
    # "healthy" would be a second, weaker classifier beside the probe's.
    # Refresh paths re-stamp ``last_checked_at`` after this call.
    dataset.source_health = None
    dataset.source_health_detail = None
    dataset.last_checked_at = None
    dataset.origin_uri = uri
    losses: list[str] = []
    if kind in _PORTAL_LINK_KINDS and all(
        ref_fields.get(k) is None for k in PORTAL_LINK_KEYS
    ):
        carried = carried_portal_link(dataset.origin_ref)
        losses = _carry_losses(dataset.origin_ref, carried, kind, ref_fields)
        if losses:
            carried = {}
        ref_fields |= carried
    dataset.origin_ref = build_origin_ref(kind, **ref_fields)
    return losses


def project_unknown(value: str | None) -> str:
    """Render a never-determined source-state column at the API boundary."""
    return UNKNOWN if value is None else value
