"""Cross-domain catalog access contract.

Defines structural Protocols that processing/* uses to read/write catalog
data without importing the concrete SQLAlchemy ORM from
app.modules.catalog.* — ORM classes satisfy them structurally (PEP 544).

Uses only stdlib types (plus AsyncSession) to avoid a core -> modules.catalog
import edge; core/ is the lowest layer and never
imports from modules/. SearchFilters and
IngestionResult are typed as unresolved forward-reference strings for the
same reason.

An enterprise overlay may replace the default implementation by
registering a port under the 'processing_port' key via the
geolens.extensions entry-point group; get_processing_port() returns it on
subsequent requests.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, NamedTuple, Protocol, runtime_checkable

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity

# An apply_manifest_maps result key: ``{"token": <raw share token>, "title":
# <map name>}`` for the map whose share link the apply minted. The raw token
# exists nowhere else, so this result is its only way to the caller.
MINTED_SHARE_KEY = "minted_share"
_SHARE_LINKS_WITHHELD = "geolens.manifest_share_links_withheld"


@contextmanager
def withholding_share_links(session: AsyncSession, withheld: bool) -> Iterator[None]:
    """With ``withheld``, tell an apply_manifest_maps run in the block that a
    share link it mints could not be returned, so it must mint none."""
    if not withheld:
        yield
        return
    session.info[_SHARE_LINKS_WITHHELD] = True
    try:
        yield
    finally:
        session.info.pop(_SHARE_LINKS_WITHHELD, None)


def share_links_withheld(session: AsyncSession) -> bool:
    """Whether a share link minted on ``session`` now could not be returned."""
    return bool(session.info.get(_SHARE_LINKS_WITHHELD))


@dataclass(frozen=True)
class ManifestGroupsPlan:
    """The groups a manifest entry shares its dataset with.

    ``group_ids`` and ``names`` are the groups it ends with. ``left_off`` are
    wanted groups that don't exist or that the caller may not add, by id
    only, since their names aren't the caller's to see. ``held_back`` names
    the groups the dataset may not gain without reaching more people, and
    ``held_back_ids`` holds their ids. ``added`` says whether it gains any
    group. ``unchanged`` means the dataset keeps its groups as they are,
    since the share was held back, and ``role_granted`` that a role grant
    keeps it restricted without groups. ``refused`` is, for a job's plan,
    the sentence the share's write would be refused with because it strands
    one of the owner's shared maps, None when it wouldn't be.
    """

    group_ids: list[uuid.UUID]
    names: list[str]
    left_off: list[uuid.UUID]
    held_back: list[str]
    added: bool
    unchanged: bool = False
    role_granted: bool = False
    held_back_ids: list[uuid.UUID] = field(default_factory=list)
    # The dataset's groups when planned.
    granted: list[uuid.UUID] = field(default_factory=list)
    refused: str | None = None


class PendingManifestDataset(NamedTuple):
    """What one of a request's manifest dataset entries publishes, for the
    maps of the same request to be judged on.

    ``visibility`` None keeps the dataset's. ``group_ids`` are the groups the
    entry shares the dataset with, held-back and left-off ones removed; None
    keeps the dataset's groups. ``role_granted`` says a role grant keeps the
    dataset restricted without groups.
    """

    visibility: str | None
    record_status: str
    title: str
    group_ids: Sequence[uuid.UUID] | None = None
    role_granted: bool = False


@runtime_checkable
class KeywordProtocol(Protocol):
    """Slim keyword contract — only ``keyword`` is read cross-domain."""

    keyword: str


@runtime_checkable
class TranslationProtocol(Protocol):
    """Localized record text included in embedding content."""

    language: str
    title: str
    summary: str | None


@runtime_checkable
class AttributeProtocol(Protocol):
    """Slim attribute metadata contract — fields read by metadata_service."""

    is_current: bool
    field_name: str
    description: str | None
    data_type: str | None


@runtime_checkable
class RecordProtocol(Protocol):
    """Catalog Record surface read by processing/*."""

    id: uuid.UUID
    title: str
    summary: str | None
    keywords: Sequence[KeywordProtocol]
    translations: Sequence[TranslationProtocol]
    spatial_extent: Any  # geoalchemy2 type — Any keeps core/ free of geoalchemy2 import
    lineage_summary: str | None
    # Analysis provenance, written by processing/analysis.
    derived_from: dict | None
    source_organization: str | None
    access_constraints: str | None
    temporal_start: date | None
    temporal_end: date | None
    record_type: str
    created_at: datetime


@runtime_checkable
class DatasetProtocol(Protocol):
    """Catalog Dataset surface read by processing/*."""

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    record_id: uuid.UUID
    table_name: str
    geometry_type: str | None
    feature_count: int | None
    srid: int | None
    original_srid: int | None
    source_format: str | None
    source_filename: str | None
    source_url: str | None
    column_info: list | None
    sample_values: dict | None
    quality_detail: dict | None
    quality_statement: str | None
    current_version: int
    tile_cache_version: int
    is_3d: bool | None
    record: RecordProtocol
    attributes: Sequence[AttributeProtocol]


@runtime_checkable
class MapProtocol(Protocol):
    """Catalog Map surface read by processing/ai."""

    id: uuid.UUID
    created_by: uuid.UUID | None
    basemap_style: str
    name: str


@runtime_checkable
class DatasetGrantProtocol(Protocol):
    """Catalog DatasetGrant surface — used for type annotations only.

    InstrumentedAttribute SQL uses pass the concrete ORM class as
    ``grant_cls: Any``.
    """

    id: uuid.UUID
    dataset_id: uuid.UUID
    role_id: uuid.UUID


@runtime_checkable
class DatasetVersionProtocol(Protocol):
    """Catalog DatasetVersion surface — only ``id`` is read by reupload finalize path."""

    id: uuid.UUID


# Shorter aliases for caller annotations.
# Both names are exported; ``Dataset`` reads cleaner in parameter annotations
# and ``DatasetProtocol`` is preferred in conformance assertions.
Dataset = DatasetProtocol
Record = RecordProtocol
Map = MapProtocol
DatasetGrant = DatasetGrantProtocol
DatasetVersion = DatasetVersionProtocol
Keyword = KeywordProtocol
Translation = TranslationProtocol
Attribute = AttributeProtocol


@runtime_checkable
class ProcessingPort(Protocol):
    """Comprehensive catalog accessor contract used by backend/app/processing/*.

    Mirrors IdentityProtocol's "single comprehensive Protocol"
    shape: every cross-domain catalog accessor processing/* needs
    is on this surface. Companion structural Protocols (DatasetProtocol,
    etc.) above type the ORM-shaped return values without leaking
    SQLAlchemy ORM into core/.

    SearchFilters and IngestionResult are typed as Any / forward-reference
    strings — they live in app.modules.* and can't be imported here.
    DefaultProcessingPort in platform/extensions/defaults.py
    has full typed access.
    """

    async def get_dataset(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> DatasetProtocol | None: ...

    async def get_record(
        self, session: AsyncSession, record_id: uuid.UUID
    ) -> RecordProtocol | None: ...

    async def search_datasets(
        self,
        session: AsyncSession,
        user: Identity | None,
        user_roles: set[str],
        filters: Any,  # SearchFilters — typed Any; concrete type in app.modules.*
    ) -> tuple[list[DatasetProtocol], int]: ...

    def apply_visibility_filter(
        self,
        stmt: Select,
        user: Identity | None,
        user_roles: set[str],
        record_cls: Any,
        grant_cls: Any | None = None,
    ) -> Select: ...

    async def check_dataset_access(
        self,
        session: AsyncSession,
        dataset: Any,
        dataset_id: uuid.UUID,
        user: Identity,
        *,
        user_roles: set[str] | None = None,
    ) -> set[str]: ...

    async def check_dataset_write_access(
        self,
        session: AsyncSession,
        dataset: Any,
        dataset_id: uuid.UUID,
        user: Identity,
        *,
        user_roles: set[str] | None = None,
    ) -> set[str]: ...

    async def get_user_roles(
        self, session: AsyncSession, user: Identity
    ) -> set[str]: ...

    # A VRT serves its members' pixels to its own audience, which the tile path
    # and the build tasks compare against each member's. ``vrt`` is a
    # ``RecordAudienceQuery``, typed Any since core/ may not import platform/.
    async def vrt_members_beyond_audience(
        self, session: AsyncSession, member_ids: Sequence[uuid.UUID], vrt: Any
    ) -> list[uuid.UUID]: ...

    # REQUIRED (EXTENSION_API_VERSION 17 -> 18): the batch tile-token endpoint
    # asks once for every mosaic in the batch. Each item is ``(vrt,
    # member_ids)``; the answer says, per item, whether a member is beyond the
    # VRT's audience, as ``vrt_members_beyond_audience`` would.
    async def vrts_beyond_member_audience(
        self,
        session: AsyncSession,
        vrts: Sequence[tuple[Any, Sequence[uuid.UUID]]],
    ) -> list[bool]: ...

    async def run_analysis_preview(
        self,
        session: AsyncSession,
        dataset: Any,
        operation: str,
        *,
        user_id: uuid.UUID,
        distance_meters: float | None = None,
        mask: dict[str, Any] | None = None,
        # The clip mask can come from another dataset, not just a
        # drawn polygon. Passed as the loaded object, not an id, because the
        # caller owns its visibility check, as it owns the source dataset's.
        mask_dataset: Any | None = None,
    ) -> Any: ...  # -> AnalysisPreviewResponse

    async def get_column_stats(
        self,
        session: AsyncSession,
        table_name: str,
        column_name: str,
        *,
        class_count: int = 5,
        allowed_tables: set[str] | None = None,
    ) -> dict: ...

    async def get_distinct_values(
        self,
        session: AsyncSession,
        table_name: str,
        column_name: str,
        limit: int = 100,
        *,
        allowed_tables: set[str] | None = None,
    ) -> list: ...

    async def get_column_null_cardinality(
        self,
        session: AsyncSession,
        table_name: str,
        columns: list[str],
        *,
        allowed_tables: set[str] | None = None,
        max_columns: int = 20,
        sample_size: int = 10000,
    ) -> dict[str, dict]: ...

    def extract_bbox(self, dataset: DatasetProtocol) -> list[float] | None: ...

    # Implementations must eagerly populate both ``keywords`` and
    # ``translations``: embedding backfills consume them after query
    # execution and the community ORM deliberately uses lazy="raise".
    #
    # With ``force=False`` the contract is "records with no vector
    # under the ACTIVE embedding model", not "records with no vector at all" —
    # an implementation that can't resolve the active model must return an
    # empty list; returning everything hands the whole catalog to a run that
    # cannot store what it embeds.
    async def get_records_without_embeddings(
        self, session: AsyncSession, *, force: bool = False
    ) -> list[RecordProtocol]: ...

    async def get_datasets_meta_by_ids(
        self, session: AsyncSession, ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, str, str | None]]: ...

    async def get_catalog_vocabulary(
        self,
        session: AsyncSession,
        *,
        user: Identity | None,
        user_roles: set[str],
    ) -> list[str]:
        """Distinct keywords of the records ``user`` may read."""
        ...

    async def get_keywords_for_records(
        self,
        session: AsyncSession,
        record_ids: list[uuid.UUID],
        *,
        user: Identity | None,
        user_roles: set[str],
    ) -> list[str]:
        """Distinct keywords of those ``record_ids`` that ``user`` may read."""
        ...

    async def get_record_keyword_count(
        self, session: AsyncSession, record_id: uuid.UUID
    ) -> int: ...

    async def get_attribute_metadata(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> list[AttributeProtocol]: ...

    async def get_dataset_version(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> DatasetVersionProtocol | None: ...

    async def create_dataset(
        self,
        session: AsyncSession,
        table_name: str,
        title: str,
        created_by: uuid.UUID,
        *,
        summary: str | None = None,
        visibility: str = "private",
        ingestion: Any = None,  # IngestionResult | None — typed Any; concrete type in app.modules.*
    ) -> DatasetProtocol: ...

    async def create_map(
        self,
        session: AsyncSession,
        name: str,
        description: str | None,
        created_by: uuid.UUID,
        notes: str | None = None,
    ) -> MapProtocol: ...

    async def update_map(
        self,
        session: AsyncSession,
        map_id: uuid.UUID,
        **kwargs: Any,
    ) -> tuple[MapProtocol, list[Any], str | None, str | None]: ...

    async def update_dataset_metadata(
        self,
        session: AsyncSession,
        dataset_id: uuid.UUID,
        fields: dict[str, Any],
        *,
        actor_id: uuid.UUID,
    ) -> None:
        """Apply ``fields`` as the metadata PATCH body would, with its checks.

        Raises ``ValueError`` for a change the PATCH would refuse. Does not
        commit.
        """
        ...

    def create_ingestion_result(self, **kwargs: Any) -> Any: ...  # -> IngestionResult

    # The refresh/reupload paths can change a dataset's modality,
    # so the auto-generated `record_distributions` rows must be reconciled —
    # that logic belongs beside `generate_distributions` in the catalog
    # domain, which processing/ may not import. Returns the rows created and
    # the (distribution_type, format) pairs removed, typed Any for the same
    # reason.
    async def reconcile_distributions(
        self,
        session: AsyncSession,
        dataset_id: uuid.UUID,
        record_id: uuid.UUID,
        table_name: str,
        geometry_type: str | None = None,
    ) -> tuple[list[Any], list[tuple[str, str]]]: ...

    def build_gdal_source(
        self,
        service_type: str,
        base_url: str,
        layer_name: str,
        layer_id: int | str | None = None,
        token: str | None = None,
        order_field: str | None = None,
        result_limit: int | None = None,
        result_offset: int | None = None,
        object_ids: list[int] | tuple[int, ...] | None = None,
        force_arcgis_geojson: bool = False,
        return_z: bool = False,
    ) -> tuple[str, str]: ...

    async def fetch_arcgis_id_plan(
        self,
        base_url: str,
        layer_id: int | str,
        client: Any,
        token: str | None = None,
        *,
        expected_oid_field: str | None = None,
        current_version: str | None = None,
    ) -> Any: ...

    # ORM class helpers: let processing/* call sites pass concrete ORM
    # classes to select()/session.add() without importing app.modules.catalog.*
    # directly. This respects the core/ layering since the Protocol declares
    # only a `type` return, no modules.* import.
    def get_record_orm_class(self) -> type: ...

    def get_grant_orm_class(self) -> type: ...

    def get_dataset_orm_class(self) -> type: ...

    def get_retired_table_name_orm_class(self) -> type: ...

    def get_dataset_version_orm_class(self) -> type: ...

    def get_record_distribution_orm_class(self) -> type: ...

    # The swap path recomputes schema drift against the staging
    # table rather than trusting the preview, which may be minutes stale for a
    # live service. The function is pure but lives in the catalog domain, and
    # processing/ may not import it directly.
    def compute_schema_diff(
        self,
        old_columns: list[dict],
        new_columns: list[dict],
        old_feature_count: int | None,
        new_feature_count: int | None,
    ) -> dict: ...

    def get_attribute_metadata_orm_class(self) -> type: ...

    # The STAC refresh strategy re-reads the item document its
    # asset was published in, through Rule 2's safe client and the
    # health classifier — both live in the catalog domain, so the strategy
    # asks for the answer through this port and holds no HTTP client of its
    # own. Returns a ``StacResolution``, typed Any since core/ may not
    # import modules.*.
    # ``credential`` is the ``ServiceCredential`` a credentialed
    # refresh claimed for this attempt, and ``catalog_origin`` the catalog
    # address it was given for; a read steered elsewhere is made anonymously.
    # ``repair_nodata`` asks the resolver to read an unmoved asset's nodata,
    # band count and data type, for whichever the caller has not stored.
    async def resolve_stac_binding(
        self,
        *,
        item_href: str,
        item_id: str | None,
        collection_id: str | None,
        asset_href: str | None,
        asset_key: str | None,
        credential: Any = None,
        catalog_origin: str | None = None,
        repair_nodata: bool = False,
    ) -> Any: ...

    # Preserves joinedload semantics for metadata_service._build_dataset_context.
    async def get_dataset_with_attributes(
        self, session: AsyncSession, dataset_id: uuid.UUID
    ) -> DatasetProtocol | None: ...

    # Publish manifest v2. Collection refusals come back as the warning code
    # "A033" rather than raising, and a collection row that stays locked as
    # "collection_busy"; ``user`` is an Identity, ``ref`` is ``{"id": ...}``
    # or ``{"name": ...}``. ``may_create=False`` writes nothing and answers a
    # name the caller could create with ``(None, None)``.
    async def resolve_manifest_collection(
        self,
        session: AsyncSession,
        ref: Any,
        user: Identity,
        *,
        may_create: bool,
    ) -> tuple[uuid.UUID | None, str | None]: ...

    async def add_dataset_to_manifest_collection(
        self,
        session: AsyncSession,
        collection_id: uuid.UUID,
        dataset_id: uuid.UUID,
        user: Identity,
    ) -> str | None: ...

    # The groups a manifest entry would share its dataset with, None for one
    # it creates, once the entry writes ``level`` (None keeps the dataset's),
    # as the caller's roles and a publish key allow. With ``planned_from``
    # and ``granted_at_plan``, the dataset's visibility and groups when a job
    # still to publish planned the share, the answer is what that job would
    # share now, as ``apply_manifest_groups`` judges it, including whether
    # its write would strand a shared map (``refused``) once the dataset is at
    # ``level`` and ``record_status`` (None keeps its own). Writes nothing.
    async def plan_manifest_groups(
        self,
        session: AsyncSession,
        dataset_id: uuid.UUID | None,
        group_ids: Sequence[uuid.UUID],
        user: Identity,
        *,
        level: str | None,
        planned_from: str | None = None,
        granted_at_plan: Sequence[uuid.UUID] | None = None,
        record_status: str | None = None,
    ) -> ManifestGroupsPlan: ...

    # Shares a dataset a manifest job publishes with the groups it may, in the
    # publish transaction. ``audience_before`` is its visibility before the
    # publish, None when the job created it, ``planned_from`` its visibility
    # and ``granted_at_plan`` its groups when the apply planned the share.
    # Returns the plan and, when the share was refused, the refusal as a
    # sentence to show, else None. A refused share leaves the groups as they
    # were, as a held-back one does, and fails nothing here.
    async def apply_manifest_groups(
        self,
        session: AsyncSession,
        dataset_id: uuid.UUID,
        group_ids: Sequence[uuid.UUID],
        user: Identity,
        *,
        audience_before: str | None,
        planned_from: str | None,
        granted_at_plan: Sequence[uuid.UUID] | None,
    ) -> tuple[ManifestGroupsPlan, str | None]: ...

    # The sentence a manifest job's publication of ``visibility`` and
    # ``record_status`` (None keeps the dataset's) is refused with for
    # stranding one of the owner's shared maps while the dataset's group
    # grants are ``group_ids`` (None keeps the stored ones), as the metadata
    # edit the job makes judges it; None when it isn't. Writes nothing.
    async def manifest_publication_refusal(
        self,
        session: AsyncSession,
        dataset_id: uuid.UUID,
        *,
        visibility: str | None,
        record_status: str | None,
        group_ids: Sequence[uuid.UUID] | None,
    ) -> str | None: ...

    # The names of a dataset's groups, None when ``user`` may not see them.
    async def manifest_dataset_group_names(
        self, session: AsyncSession, dataset_id: uuid.UUID, user: Identity
    ) -> list[str] | None: ...

    # Returns the ``source_name`` of every entry that matched no column.
    async def apply_manifest_attributes(
        self,
        session: AsyncSession,
        dataset_id: uuid.UUID,
        attributes: Sequence[Any],
        *,
        actor_id: uuid.UUID,
    ) -> list[str]: ...

    # ``maps`` are the request's ``ManifestMap`` entries and
    # ``dataset_ids_by_key`` the dataset each layer ``dataset_key`` names,
    # resolved by the caller; a key it couldn't resolve is absent.
    # ``pending_datasets`` are the request's own dataset entries that change
    # their dataset, by key and by dataset id, each with the visibility,
    # record status, title and groups it publishes; a dry run judges a map on
    # them. ``unsettled_dataset_ids`` are datasets a job is still
    # replacing, which a layer may not use yet. ``public_fallback`` and
    # ``client`` are the request's. Outside a dry run each map that checks
    # clean is written and committed on its own. Returns one
    # ``ManifestMapResult``-shaped dict per map, in order. A map whose apply
    # minted its share link may also carry ``MINTED_SHARE_KEY``, which the
    # caller removes before the result reaches a response model. Under
    # ``withholding_share_links`` a map that would mint one mints none and
    # answers info A074 instead.
    async def apply_manifest_maps(
        self,
        session: AsyncSession,
        maps: Sequence[Any],
        user: Identity,
        *,
        dry_run: bool,
        dataset_ids_by_key: Mapping[str, uuid.UUID],
        pending_datasets: Mapping[str | uuid.UUID, PendingManifestDataset],
        unsettled_dataset_ids: Collection[uuid.UUID],
        public_fallback: str | None,
        client: Any,
        ip_address: str | None,
    ) -> list[dict[str, Any]]: ...
