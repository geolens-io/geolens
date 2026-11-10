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
- ``restamp`` writes a ``SourceBinding`` (format, pointer and allowlisted
  payload) onto a dataset in one call, with the contact and freshness the
  caller states.
- ``read_source`` is the typed read of a stored binding: what a refresh or
  probe of each kind can use, or which key it lacks.
- ``bound_pointer`` and ``still_bound`` answer "is the dataset still bound to
  what I read?": a snapshot of the stored binding, and the SQL predicate a
  guarded write runs under so it lands only while that snapshot still holds.
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

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal, NamedTuple

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement

from app.core.record_types import RASTER_FAMILY_RECORD_TYPES
from app.platform.portal_link import (
    LOSS_LINK_UNSUPPORTED,
    LOSS_PORTAL_URL_DOMAIN_MISMATCH,
    resolve_portal_link,
    same_registrable_domain,
)

# Kinds whose import or refresh reads the data from its origin, so a
# successful one dates the contact.
CONTACTED_ORIGIN_KINDS: frozenset[str] = frozenset({"service", "stac", "database"})

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
    {"upload", "postgis", "service", "stac", "created", "database"}
)

# The same vocabulary as a request-model annotation, so a door that takes an
# origin kind as INPUT rejects an unknown one at the schema boundary and
# publishes the closed set in OpenAPI. `test_reupload_expected_origin_1768.py`
# asserts the two agree.
OriginKind = Literal["upload", "postgis", "service", "stac", "created", "database"]

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
    # kind carries them too, and `restamp` keeps them across every restamp of
    # either kind.
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
    # A table read through an operator-configured database connection. The
    # connection NAME is the identity; its host and login stay in the
    # deployment's settings, so neither can reach this column.
    "database": frozenset({"connection", "schema", "table"}),
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
    if source_format == "database":
        return "database"
    if source_format in SERVICE_SOURCE_FORMATS:
        return "service"
    return "upload"


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


@dataclass(frozen=True)
class ServiceSource:
    """A service binding complete enough to re-pull one layer."""

    service_type: str
    url: str
    layer_id: str
    auth_required: bool


@dataclass(frozen=True)
class StacSource:
    """A STAC binding that names the item document to re-resolve.

    ``catalog_url`` is the stored ``url`` key: the catalog root the caller
    submitted at import.
    """

    item_href: str
    item_id: str | None
    collection_id: str | None
    asset_href: str | None
    asset_key: str | None
    catalog_url: str | None
    auth_required: bool


@dataclass(frozen=True)
class PostgisSource:
    """A registered table's binding: its schema-qualified name."""

    table_name: str


@dataclass(frozen=True)
class DatabaseSource:
    """A table behind an operator-configured database connection, by name."""

    connection: str
    schema: str
    table: str

    def ref(self) -> dict[str, str]:
        return {
            "connection": self.connection,
            "schema": self.schema,
            "table": self.table,
        }

    @property
    def uri(self) -> str:
        return database_origin_uri(self.connection, self.schema, self.table)


@dataclass(frozen=True)
class Unavailable:
    """A binding of ``kind`` that lacks ``missing``, or holds it unusably."""

    kind: str
    missing: str


def _stored_text(ref: dict[str, Any], key: str) -> str | None:
    value = ref.get(key)
    return value if isinstance(value, str) else None


def _read_service(ref: dict[str, Any]) -> ServiceSource | Unavailable:
    service_type = _stored_text(ref, "service_type")
    if service_type not in SERVICE_SOURCE_FORMATS:
        return Unavailable("service", "service_type")
    url = _stored_text(ref, "url")
    if not url:
        return Unavailable("service", "url")
    layer_id = ref.get("layer_id")
    if isinstance(layer_id, int) and not isinstance(layer_id, bool):
        layer_id = str(layer_id)
    if not isinstance(layer_id, str):
        return Unavailable("service", "layer_id")
    return ServiceSource(
        service_type=service_type,
        url=url,
        layer_id=layer_id,
        auth_required=service_auth_required(ref),
    )


def _read_stac(ref: dict[str, Any]) -> StacSource | Unavailable:
    item_href = _stored_text(ref, "item_href")
    if not item_href:
        return Unavailable("stac", "item_href")
    return StacSource(
        item_href=item_href,
        item_id=_stored_text(ref, "item_id"),
        collection_id=_stored_text(ref, "collection_id"),
        asset_href=_stored_text(ref, "asset_href"),
        asset_key=_stored_text(ref, "asset_key"),
        catalog_url=_stored_text(ref, "url"),
        auth_required=service_auth_required(ref),
    )


def _read_postgis(ref: dict[str, Any]) -> PostgisSource | Unavailable:
    table_name = _stored_text(ref, "table_name")
    if not table_name:
        return Unavailable("postgis", "table_name")
    return PostgisSource(table_name=table_name)


def _read_database(ref: dict[str, Any]) -> DatabaseSource | Unavailable:
    fields = {}
    for key in ("connection", "schema", "table"):
        value = _stored_text(ref, key)
        if not value:
            return Unavailable("database", key)
        fields[key] = value
    return DatabaseSource(**fields)


def read_source(
    kind: str | None, origin_ref: Any
) -> ServiceSource | StacSource | PostgisSource | DatabaseSource | Unavailable | None:
    """The stored binding of an origin ``kind``, typed, or the key it lacks.

    ``None`` for a kind with no source to read again (an upload, a drawn
    layer, an originless record). Keys are checked in the order a refresh
    reports them, so ``Unavailable.missing`` names the first gap. A value of
    the wrong type counts as missing, and ``auth_required`` holds only for a
    stored ``True``. Never raises HTTP; callers map ``Unavailable`` to their
    own refusals. Raises ``ValueError`` for a kind outside ``ORIGIN_KINDS``,
    so a new kind cannot pass through a reader written before it.
    """
    if kind is not None and kind not in ORIGIN_KINDS:
        raise ValueError(
            f"unknown origin kind {kind!r}; expected one of {sorted(ORIGIN_KINDS)}"
        )
    ref = origin_ref if isinstance(origin_ref, dict) else {}
    if kind == "service":
        return _read_service(ref)
    if kind == "stac":
        return _read_stac(ref)
    if kind == "postgis":
        return _read_postgis(ref)
    if kind == "database":
        return _read_database(ref)
    return None


def database_origin_uri(connection: str, schema: str, table: str) -> str:
    """The pointer of a database table: the connection name, never its host."""
    return f"database://{connection}/{schema}.{table}"


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


def clear_source_probe_state(dataset: Any) -> None:
    """Forget the stored probe verdict, for a successful ingest or refresh commit.

    The data now names a different origin, or one a pre-swap failure verdict
    is stale about. NULL (projected as unknown) is honest either way;
    "healthy" would be a second, weaker classifier beside the probe's. Refresh
    paths re-stamp ``last_checked_at`` after this call.
    """
    dataset.source_health = None
    dataset.source_health_detail = None
    dataset.last_checked_at = None


@dataclass(frozen=True)
class SourceBinding:
    """The binding columns a restamp writes together: ``source_format``, the
    ``origin_uri`` pointer (``uri``) and the ``origin_ref`` payload (``ref``).

    The kind follows ``source_format``, as ``classify_origin`` derives it.
    ``ref`` is exactly what ``build_origin_ref`` builds for that kind, so a
    binding holding an undeclared key, or a key of another kind, cannot be
    constructed. Built by the per-kind constructors, or by ``from_ref`` for a
    payload captured before the kind was known.
    """

    source_format: str | None
    uri: str | None
    ref: dict[str, Any] | None

    def __post_init__(self) -> None:
        fields = {k: v for k, v in (self.ref or {}).items() if k != "kind"}
        if build_origin_ref(self.kind, **fields) != self.ref:
            raise ValueError(f"not the {self.kind} payload the allowlist builds")

    @property
    def kind(self) -> str:
        """The origin kind ``source_format`` classifies as."""
        return classify_origin(self.source_format)

    @classmethod
    def _of(
        cls, kind: str, source_format: str | None, uri: str | None, **fields: Any
    ) -> SourceBinding:
        return cls(source_format, uri, build_origin_ref(kind, **fields))

    @classmethod
    def from_ref(
        cls,
        source_format: str | None,
        ref: dict[str, Any] | None,
        *,
        uri: str | None = None,
    ) -> SourceBinding:
        """A binding from a payload without its ``kind``, which the format decides."""
        return cls._of(
            classify_origin(source_format), source_format, uri, **(ref or {})
        )

    @classmethod
    def upload(
        cls, source_format: str, *, filename: str | None, file_hash: str | None = None
    ) -> SourceBinding:
        """An uploaded file: no remote pointer, only its name and hash."""
        return cls._of(
            "upload", source_format, None, filename=filename, file_hash=file_hash
        )

    @classmethod
    def service(
        cls,
        service_type: str,
        *,
        url: str,
        layer_id: str | None,
        enriched_uri: str | None,
        auth_required: bool = False,
        item_id: str | None = None,
        portal_url: str | None = None,
    ) -> SourceBinding:
        """A service layer: ``url`` is the base, ``enriched_uri`` the pointer.

        ``service_type`` is the dataset's format too.
        """
        return cls._of(
            "service",
            service_type,
            enriched_uri,
            service_type=service_type,
            url=url,
            layer_id=layer_id,
            auth_required=True if auth_required else None,
            item_id=item_id,
            portal_url=portal_url,
        )

    @classmethod
    def stac(
        cls,
        *,
        asset_href: str,
        item_href: str | None,
        item_id: str | None,
        collection_id: str | None,
        asset_key: str | None,
        url: str | None,
        auth_required: bool,
    ) -> SourceBinding:
        """A STAC item's asset; the pointer is the asset href.

        The duplicate-source guard keys on ``asset_href``, so pointer and key
        are built from one value.
        """
        return cls._of(
            "stac",
            "stac",
            asset_href,
            url=url,
            asset_href=asset_href,
            item_href=item_href,
            item_id=item_id,
            collection_id=collection_id,
            asset_key=asset_key,
            auth_required=True if auth_required else None,
        )

    @classmethod
    def postgis(
        cls, table_name: str, *, schema: str, managed: bool = False
    ) -> SourceBinding:
        """A registered table: pointer and ``table_name`` from one qualified name.

        ``schema`` is passed in, not derived from ``dataset.tenant_id``: in
        multi-tenant mode the INSERT sends ``tenant_id`` as NULL and a trigger
        fills it from a GUC, so the ORM attribute stays None and deriving it
        would point every multi-tenant registration at the wrong schema.

        An unmanaged registration's ref carries no ``managed`` key; every
        reader goes through :func:`geolens_owns_table`.
        """
        qualified = f"{schema}.{table_name}"
        return cls._of(
            "postgis",
            None,
            f"postgis://{qualified}",
            table_name=qualified,
            managed=True if managed else None,
        )

    @classmethod
    def database(cls, connection: str, *, schema: str, table: str) -> SourceBinding:
        """A table read through a database connection: no host, no login."""
        source = DatabaseSource(connection, schema, table)
        return cls._of("database", "database", source.uri, **source.ref())

    @classmethod
    def created(cls) -> SourceBinding:
        """A layer drawn in the app: no pointer and no payload."""
        return cls._of("created", "created", None)


class Keep(Enum):
    """Leave a column as it is: ``restamp(..., refreshed_at=KEEP)``."""

    KEEP = "keep"


KEEP = Keep.KEEP


def restamp(
    dataset: Any,
    binding: SourceBinding,
    *,
    contacted_at: datetime | None,
    refreshed_at: datetime | None | Keep,
    health: tuple[str, str | None] | None = None,
) -> list[str]:
    """Point a Dataset ORM instance at ``binding``.

    The only writer of ``origin_uri``/``origin_ref``, which move with
    ``source_format`` in this one call. Neither column appears in
    ``_DATASET_FIELD_MAP``, so the metadata PATCH cannot reach them. Call it
    where the data the binding describes is published: the transaction that
    creates the dataset, or a swap's publication success block.

    Clears the probe state, then writes ``health`` (verdict, detail) when
    given. ``last_checked_at`` becomes ``contacted_at`` and
    ``last_refreshed_at`` becomes ``refreshed_at`` unless that is ``KEEP``.
    Both are the caller's to say: doors date contact and freshness
    differently on purpose.

    A service or upload binding naming no portal link keeps the one the
    dataset holds. Returns the loss codes of a link dropped instead, when a
    service binding's host no longer shares its domain.
    """
    old_ref = dataset.origin_ref
    ref = binding.ref
    losses: list[str] = []
    kind = binding.kind
    if kind in _PORTAL_LINK_KINDS and not any(k in ref for k in PORTAL_LINK_KEYS):
        carried = carried_portal_link(old_ref)
        losses = _carry_losses(old_ref, carried, kind, ref)
        if carried and not losses:
            fields = {k: v for k, v in ref.items() if k != "kind"}
            ref = build_origin_ref(kind, **fields, **carried)
    dataset.source_format = binding.source_format
    dataset.origin_uri = binding.uri
    dataset.origin_ref = ref
    clear_source_probe_state(dataset)
    if health is not None:
        dataset.source_health, dataset.source_health_detail = health
    dataset.last_checked_at = contacted_at
    if refreshed_at is not KEEP:
        dataset.last_refreshed_at = refreshed_at
    return losses


class BoundPointer(NamedTuple):
    """A dataset's stored ``(origin_uri, origin_ref, source_format)``, as read.

    Two pointers are the same binding only when all three are equal, the
    whole ``origin_ref`` included, so an ``auth_required`` flip or a new
    portal link counts as a rebind.
    """

    origin_uri: str | None
    origin_ref: dict[str, Any] | None
    source_format: str | None


def bound_pointer(dataset: Any) -> BoundPointer:
    """Snapshot the binding a Dataset ORM instance holds now."""
    return BoundPointer(dataset.origin_uri, dataset.origin_ref, dataset.source_format)


def still_bound(
    dataset_cls: Any, dataset_id: Any, pointer: BoundPointer
) -> ColumnElement[bool]:
    """WHERE clause matching the dataset only while it holds ``pointer`` exactly.

    The caller keeps its own statement, so it can add ``RETURNING`` or lock
    options. ``origin_ref`` is compared as JSONB, so key order is not a change.
    """
    origin_uri, origin_ref, source_format = pointer
    return and_(
        dataset_cls.id == dataset_id,
        dataset_cls.origin_uri.is_not_distinct_from(origin_uri),
        dataset_cls.origin_ref.is_not_distinct_from(origin_ref),
        dataset_cls.source_format.is_not_distinct_from(source_format),
    )


def project_unknown(value: str | None) -> str:
    """Render a never-determined source-state column at the API boundary."""
    return UNKNOWN if value is None else value
