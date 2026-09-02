from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.collection_ref import CollectionRef
    from ..models.column_info import ColumnInfo
    from ..models.dataset_response_origin_ref_type_0 import (
        DatasetResponseOriginRefType0,
    )
    from ..models.dataset_response_stac_assets_type_0 import (
        DatasetResponseStacAssetsType0,
    )
    from ..models.derived_from_response import DerivedFromResponse
    from ..models.quality_detail import QualityDetail
    from ..models.raster_metadata import RasterMetadata


T = TypeVar("T", bound="DatasetResponse")


@_attrs_define
class DatasetResponse:
    """
    Attributes:
        id (UUID):
        record_id (UUID): Parent catalog record UUID
        table_name (str): Internal PostGIS table name
        title (str):
        summary (None | str):
        feature_count (int | None):
        source_filename (None | str):
        visibility (str): Access level: private, restricted, internal, public
        created_by (None | UUID):
        created_by_display (str):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
        srid (int | None | Unset): Current EPSG SRID of stored geometry
        geometry_type (None | str | Unset): OGC geometry type, e.g. MultiPolygon
        has_generic_geometry (bool | Unset): True when the underlying column is generic GEOMETRY (created sketch
            datasets): the dataset accepts ANY geometry subtype on write regardless of the display geometry_type above.
            Computed on the detail endpoint only (fix #430 codex r18); list endpoints always report false. Default: False.
        is_3d (bool | None | Unset): True if geometry has Z dimension
        n_dims (int | None | Unset): Number of coordinate dimensions (2, 3, or 4)
        z_min (float | None | Unset): Minimum Z value across all features
        z_max (float | None | Unset): Maximum Z value across all features
        extent_bbox (list[float] | None | Unset): Bounding box [west, south, east, north] per RFC 7946 §5.2. west > east
            on an antimeridian-crossing extent.
        column_info (list[ColumnInfo] | None | Unset): Column names, types, and stats
        license_ (None | str | Unset):
        attribution (None | str | Unset): Credit line the source's terms require to be displayed wherever the data is
            rendered. Shown verbatim in the map viewer's attribution control.
        source_organization (None | str | Unset):
        data_vintage_start (datetime.date | None | Unset): Start of temporal coverage
        data_vintage_end (datetime.date | None | Unset): End of temporal coverage
        quality_detail (None | QualityDetail | Unset): Automated quality assessment results
        source_format (None | str | Unset): Original file format, e.g. GPKG, SHP
        tile_columns (list[str] | None | Unset): Ordered vector-tile property allowlist; null uses zoom defaults, []
            emits geometry-only tiles, list emits those properties at any zoom.
        original_srid (int | None | Unset): EPSG SRID of the uploaded source file
        current_version (int | Unset): Monotonic version counter Default: 1.
        source_url (None | str | Unset): URL the data was originally fetched from
        origin (None | str | Unset): How the data entered the catalog: upload, postgis, service, stac, or created.
            Computed from source_format and record_type, not stored; null for collections and VRTs, which have no origin of
            their own.
        origin_uri (None | str | Unset): Machine-readable pointer back to the origin, written only by ingest and
            refresh. Distinct from source_url, which is editable descriptive metadata. Null for uploads and created
            datasets. feat(#1316): also null for any reader who is neither the dataset's owner nor an admin — origin (above)
            and the freshness/health fields below are not gated and still describe the dataset's capabilities.
        origin_ref (DatasetResponseOriginRefType0 | None | Unset): Typed per-origin payload with a `kind` discriminator,
            e.g. {"kind": "service", "service_type": "wfs", "url": "...", "layer_id": "0"}. Never contains credentials.
            feat(#1316): owner-or-admin only, same redaction as origin_uri.
        last_refreshed_at (datetime.datetime | None | Unset): Last committed successful refresh — not the last attempt
        last_checked_at (datetime.datetime | None | Unset): Last time GeoLens contacted the origin at all, whether the
            attempt succeeded or failed
        source_health (str | Unset): healthy, missing, inaccessible, or unknown. 'unknown' means never probed, or an
            origin kind with nothing to probe. Default: 'unknown'.
        source_health_detail (None | str | Unset): Why the origin is not healthy, as one of a fixed set of GeoLens
            codes: auth_required, blocked_by_policy, item_withdrawn, network_error, not_found, server_error, timeout,
            unauthorized, unexpected_status. Null when healthy or never probed. Never provider text, a URL, or a response
            body — nothing the origin sent is stored here.
        schema_drift_status (str | Unset): none, drifted, or unknown. Set at refresh commit from the schema diff;
            'unknown' until a refresh has run. Default: 'unknown'.
        source_freshness (str | Unset): fresh, due, overdue, or unknown, computed from last_refreshed_at against the
            declared update_frequency: due past one declared period, overdue past two. 'unknown' when the origin cannot be
            refreshed at all (created), when no cadence is declared (asNeeded, irregular, notPlanned, unknown), or when
            nothing has been refreshed yet. Advisory only; never blocks an operation. Distinct from the quality score's own
            freshness, which measures quality_detail.computed_at rather than the source. Default: 'unknown'.
        quality_statement (None | str | Unset):
        last_edited_by_display (None | str | Unset):
        last_edited_at (datetime.datetime | None | Unset):
        collections (list[CollectionRef] | None | Unset):
        record_status (str | Unset): Lifecycle status. Deliberately not pinned to an enum: the values come from the
            workflow extension's status_order(), so an overlay may define its own. Community default order: draft, ready,
            internal, published. Default: 'draft'.
        lineage_summary (None | str | Unset): Free-text provenance / lineage statement
        derived_from (DerivedFromResponse | None | Unset): Provenance for an analysis output. Null for a dataset that
            was not derived, and also for a requester who cannot access the source dataset — the two are deliberately
            indistinguishable.
        update_frequency (None | str | Unset): ISO maintenance frequency code
        usage_constraints (None | str | Unset):
        access_constraints (None | str | Unset):
        sensitivity_classification (None | str | Unset): e.g. public, confidential, restricted
        theme_category (list[str] | None | Unset): ISO topic category codes
        owner_org (None | str | Unset): Owning organization name
        published_at (datetime.datetime | None | Unset):
        updated_by (None | Unset | UUID):
        record_type (str | Unset): Record type: 'vector_dataset' (spatial features), 'raster_dataset' (single COG),
            'vrt_dataset' (VRT mosaic), 'table' (non-spatial tabular), 'map' (saved map), 'service' (catalogued remote
            service), 'collection' (flat dataset group). Default: 'vector_dataset'.
        raster (None | RasterMetadata | Unset): Raster-specific metadata (null for vectors)
        stac_assets (DatasetResponseStacAssetsType0 | None | Unset): STAC-style asset dictionary
        stac_extensions (list[str] | None | Unset):
        language (None | str | Unset): ISO 639-1 language code, e.g. en, fr
        metadata_warnings (list[str] | None | Unset): Advisory warnings produced by a metadata update — e.g. a
            visibility or status change exposing keywords inherited from an analysis source the new audience cannot open
            (feat #1070). Only ever set on the PATCH response; the change has already applied.
    """

    id: UUID
    record_id: UUID
    table_name: str
    title: str
    summary: None | str
    feature_count: int | None
    source_filename: None | str
    visibility: str
    created_by: None | UUID
    created_by_display: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    srid: int | None | Unset = UNSET
    geometry_type: None | str | Unset = UNSET
    has_generic_geometry: bool | Unset = False
    is_3d: bool | None | Unset = UNSET
    n_dims: int | None | Unset = UNSET
    z_min: float | None | Unset = UNSET
    z_max: float | None | Unset = UNSET
    extent_bbox: list[float] | None | Unset = UNSET
    column_info: list[ColumnInfo] | None | Unset = UNSET
    license_: None | str | Unset = UNSET
    attribution: None | str | Unset = UNSET
    source_organization: None | str | Unset = UNSET
    data_vintage_start: datetime.date | None | Unset = UNSET
    data_vintage_end: datetime.date | None | Unset = UNSET
    quality_detail: None | QualityDetail | Unset = UNSET
    source_format: None | str | Unset = UNSET
    tile_columns: list[str] | None | Unset = UNSET
    original_srid: int | None | Unset = UNSET
    current_version: int | Unset = 1
    source_url: None | str | Unset = UNSET
    origin: None | str | Unset = UNSET
    origin_uri: None | str | Unset = UNSET
    origin_ref: DatasetResponseOriginRefType0 | None | Unset = UNSET
    last_refreshed_at: datetime.datetime | None | Unset = UNSET
    last_checked_at: datetime.datetime | None | Unset = UNSET
    source_health: str | Unset = "unknown"
    source_health_detail: None | str | Unset = UNSET
    schema_drift_status: str | Unset = "unknown"
    source_freshness: str | Unset = "unknown"
    quality_statement: None | str | Unset = UNSET
    last_edited_by_display: None | str | Unset = UNSET
    last_edited_at: datetime.datetime | None | Unset = UNSET
    collections: list[CollectionRef] | None | Unset = UNSET
    record_status: str | Unset = "draft"
    lineage_summary: None | str | Unset = UNSET
    derived_from: DerivedFromResponse | None | Unset = UNSET
    update_frequency: None | str | Unset = UNSET
    usage_constraints: None | str | Unset = UNSET
    access_constraints: None | str | Unset = UNSET
    sensitivity_classification: None | str | Unset = UNSET
    theme_category: list[str] | None | Unset = UNSET
    owner_org: None | str | Unset = UNSET
    published_at: datetime.datetime | None | Unset = UNSET
    updated_by: None | Unset | UUID = UNSET
    record_type: str | Unset = "vector_dataset"
    raster: None | RasterMetadata | Unset = UNSET
    stac_assets: DatasetResponseStacAssetsType0 | None | Unset = UNSET
    stac_extensions: list[str] | None | Unset = UNSET
    language: None | str | Unset = UNSET
    metadata_warnings: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.dataset_response_origin_ref_type_0 import (
            DatasetResponseOriginRefType0,
        )
        from ..models.dataset_response_stac_assets_type_0 import (
            DatasetResponseStacAssetsType0,
        )
        from ..models.derived_from_response import DerivedFromResponse
        from ..models.quality_detail import QualityDetail
        from ..models.raster_metadata import RasterMetadata

        id = str(self.id)

        record_id = str(self.record_id)

        table_name = self.table_name

        title = self.title

        summary: None | str
        summary = self.summary

        feature_count: int | None
        feature_count = self.feature_count

        source_filename: None | str
        source_filename = self.source_filename

        visibility = self.visibility

        created_by: None | str
        if isinstance(self.created_by, UUID):
            created_by = str(self.created_by)
        else:
            created_by = self.created_by

        created_by_display = self.created_by_display

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        srid: int | None | Unset
        if isinstance(self.srid, Unset):
            srid = UNSET
        else:
            srid = self.srid

        geometry_type: None | str | Unset
        if isinstance(self.geometry_type, Unset):
            geometry_type = UNSET
        else:
            geometry_type = self.geometry_type

        has_generic_geometry = self.has_generic_geometry

        is_3d: bool | None | Unset
        if isinstance(self.is_3d, Unset):
            is_3d = UNSET
        else:
            is_3d = self.is_3d

        n_dims: int | None | Unset
        if isinstance(self.n_dims, Unset):
            n_dims = UNSET
        else:
            n_dims = self.n_dims

        z_min: float | None | Unset
        if isinstance(self.z_min, Unset):
            z_min = UNSET
        else:
            z_min = self.z_min

        z_max: float | None | Unset
        if isinstance(self.z_max, Unset):
            z_max = UNSET
        else:
            z_max = self.z_max

        extent_bbox: list[float] | None | Unset
        if isinstance(self.extent_bbox, Unset):
            extent_bbox = UNSET
        elif isinstance(self.extent_bbox, list):
            extent_bbox = self.extent_bbox

        else:
            extent_bbox = self.extent_bbox

        column_info: list[dict[str, Any]] | None | Unset
        if isinstance(self.column_info, Unset):
            column_info = UNSET
        elif isinstance(self.column_info, list):
            column_info = []
            for column_info_type_0_item_data in self.column_info:
                column_info_type_0_item = column_info_type_0_item_data.to_dict()
                column_info.append(column_info_type_0_item)

        else:
            column_info = self.column_info

        license_: None | str | Unset
        if isinstance(self.license_, Unset):
            license_ = UNSET
        else:
            license_ = self.license_

        attribution: None | str | Unset
        if isinstance(self.attribution, Unset):
            attribution = UNSET
        else:
            attribution = self.attribution

        source_organization: None | str | Unset
        if isinstance(self.source_organization, Unset):
            source_organization = UNSET
        else:
            source_organization = self.source_organization

        data_vintage_start: None | str | Unset
        if isinstance(self.data_vintage_start, Unset):
            data_vintage_start = UNSET
        elif isinstance(self.data_vintage_start, datetime.date):
            data_vintage_start = self.data_vintage_start.isoformat()
        else:
            data_vintage_start = self.data_vintage_start

        data_vintage_end: None | str | Unset
        if isinstance(self.data_vintage_end, Unset):
            data_vintage_end = UNSET
        elif isinstance(self.data_vintage_end, datetime.date):
            data_vintage_end = self.data_vintage_end.isoformat()
        else:
            data_vintage_end = self.data_vintage_end

        quality_detail: dict[str, Any] | None | Unset
        if isinstance(self.quality_detail, Unset):
            quality_detail = UNSET
        elif isinstance(self.quality_detail, QualityDetail):
            quality_detail = self.quality_detail.to_dict()
        else:
            quality_detail = self.quality_detail

        source_format: None | str | Unset
        if isinstance(self.source_format, Unset):
            source_format = UNSET
        else:
            source_format = self.source_format

        tile_columns: list[str] | None | Unset
        if isinstance(self.tile_columns, Unset):
            tile_columns = UNSET
        elif isinstance(self.tile_columns, list):
            tile_columns = self.tile_columns

        else:
            tile_columns = self.tile_columns

        original_srid: int | None | Unset
        if isinstance(self.original_srid, Unset):
            original_srid = UNSET
        else:
            original_srid = self.original_srid

        current_version = self.current_version

        source_url: None | str | Unset
        if isinstance(self.source_url, Unset):
            source_url = UNSET
        else:
            source_url = self.source_url

        origin: None | str | Unset
        if isinstance(self.origin, Unset):
            origin = UNSET
        else:
            origin = self.origin

        origin_uri: None | str | Unset
        if isinstance(self.origin_uri, Unset):
            origin_uri = UNSET
        else:
            origin_uri = self.origin_uri

        origin_ref: dict[str, Any] | None | Unset
        if isinstance(self.origin_ref, Unset):
            origin_ref = UNSET
        elif isinstance(self.origin_ref, DatasetResponseOriginRefType0):
            origin_ref = self.origin_ref.to_dict()
        else:
            origin_ref = self.origin_ref

        last_refreshed_at: None | str | Unset
        if isinstance(self.last_refreshed_at, Unset):
            last_refreshed_at = UNSET
        elif isinstance(self.last_refreshed_at, datetime.datetime):
            last_refreshed_at = self.last_refreshed_at.isoformat()
        else:
            last_refreshed_at = self.last_refreshed_at

        last_checked_at: None | str | Unset
        if isinstance(self.last_checked_at, Unset):
            last_checked_at = UNSET
        elif isinstance(self.last_checked_at, datetime.datetime):
            last_checked_at = self.last_checked_at.isoformat()
        else:
            last_checked_at = self.last_checked_at

        source_health = self.source_health

        source_health_detail: None | str | Unset
        if isinstance(self.source_health_detail, Unset):
            source_health_detail = UNSET
        else:
            source_health_detail = self.source_health_detail

        schema_drift_status = self.schema_drift_status

        source_freshness = self.source_freshness

        quality_statement: None | str | Unset
        if isinstance(self.quality_statement, Unset):
            quality_statement = UNSET
        else:
            quality_statement = self.quality_statement

        last_edited_by_display: None | str | Unset
        if isinstance(self.last_edited_by_display, Unset):
            last_edited_by_display = UNSET
        else:
            last_edited_by_display = self.last_edited_by_display

        last_edited_at: None | str | Unset
        if isinstance(self.last_edited_at, Unset):
            last_edited_at = UNSET
        elif isinstance(self.last_edited_at, datetime.datetime):
            last_edited_at = self.last_edited_at.isoformat()
        else:
            last_edited_at = self.last_edited_at

        collections: list[dict[str, Any]] | None | Unset
        if isinstance(self.collections, Unset):
            collections = UNSET
        elif isinstance(self.collections, list):
            collections = []
            for collections_type_0_item_data in self.collections:
                collections_type_0_item = collections_type_0_item_data.to_dict()
                collections.append(collections_type_0_item)

        else:
            collections = self.collections

        record_status = self.record_status

        lineage_summary: None | str | Unset
        if isinstance(self.lineage_summary, Unset):
            lineage_summary = UNSET
        else:
            lineage_summary = self.lineage_summary

        derived_from: dict[str, Any] | None | Unset
        if isinstance(self.derived_from, Unset):
            derived_from = UNSET
        elif isinstance(self.derived_from, DerivedFromResponse):
            derived_from = self.derived_from.to_dict()
        else:
            derived_from = self.derived_from

        update_frequency: None | str | Unset
        if isinstance(self.update_frequency, Unset):
            update_frequency = UNSET
        else:
            update_frequency = self.update_frequency

        usage_constraints: None | str | Unset
        if isinstance(self.usage_constraints, Unset):
            usage_constraints = UNSET
        else:
            usage_constraints = self.usage_constraints

        access_constraints: None | str | Unset
        if isinstance(self.access_constraints, Unset):
            access_constraints = UNSET
        else:
            access_constraints = self.access_constraints

        sensitivity_classification: None | str | Unset
        if isinstance(self.sensitivity_classification, Unset):
            sensitivity_classification = UNSET
        else:
            sensitivity_classification = self.sensitivity_classification

        theme_category: list[str] | None | Unset
        if isinstance(self.theme_category, Unset):
            theme_category = UNSET
        elif isinstance(self.theme_category, list):
            theme_category = self.theme_category

        else:
            theme_category = self.theme_category

        owner_org: None | str | Unset
        if isinstance(self.owner_org, Unset):
            owner_org = UNSET
        else:
            owner_org = self.owner_org

        published_at: None | str | Unset
        if isinstance(self.published_at, Unset):
            published_at = UNSET
        elif isinstance(self.published_at, datetime.datetime):
            published_at = self.published_at.isoformat()
        else:
            published_at = self.published_at

        updated_by: None | str | Unset
        if isinstance(self.updated_by, Unset):
            updated_by = UNSET
        elif isinstance(self.updated_by, UUID):
            updated_by = str(self.updated_by)
        else:
            updated_by = self.updated_by

        record_type = self.record_type

        raster: dict[str, Any] | None | Unset
        if isinstance(self.raster, Unset):
            raster = UNSET
        elif isinstance(self.raster, RasterMetadata):
            raster = self.raster.to_dict()
        else:
            raster = self.raster

        stac_assets: dict[str, Any] | None | Unset
        if isinstance(self.stac_assets, Unset):
            stac_assets = UNSET
        elif isinstance(self.stac_assets, DatasetResponseStacAssetsType0):
            stac_assets = self.stac_assets.to_dict()
        else:
            stac_assets = self.stac_assets

        stac_extensions: list[str] | None | Unset
        if isinstance(self.stac_extensions, Unset):
            stac_extensions = UNSET
        elif isinstance(self.stac_extensions, list):
            stac_extensions = self.stac_extensions

        else:
            stac_extensions = self.stac_extensions

        language: None | str | Unset
        if isinstance(self.language, Unset):
            language = UNSET
        else:
            language = self.language

        metadata_warnings: list[str] | None | Unset
        if isinstance(self.metadata_warnings, Unset):
            metadata_warnings = UNSET
        elif isinstance(self.metadata_warnings, list):
            metadata_warnings = self.metadata_warnings

        else:
            metadata_warnings = self.metadata_warnings

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "record_id": record_id,
                "table_name": table_name,
                "title": title,
                "summary": summary,
                "feature_count": feature_count,
                "source_filename": source_filename,
                "visibility": visibility,
                "created_by": created_by,
                "created_by_display": created_by_display,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
        if srid is not UNSET:
            field_dict["srid"] = srid
        if geometry_type is not UNSET:
            field_dict["geometry_type"] = geometry_type
        if has_generic_geometry is not UNSET:
            field_dict["has_generic_geometry"] = has_generic_geometry
        if is_3d is not UNSET:
            field_dict["is_3d"] = is_3d
        if n_dims is not UNSET:
            field_dict["n_dims"] = n_dims
        if z_min is not UNSET:
            field_dict["z_min"] = z_min
        if z_max is not UNSET:
            field_dict["z_max"] = z_max
        if extent_bbox is not UNSET:
            field_dict["extent_bbox"] = extent_bbox
        if column_info is not UNSET:
            field_dict["column_info"] = column_info
        if license_ is not UNSET:
            field_dict["license"] = license_
        if attribution is not UNSET:
            field_dict["attribution"] = attribution
        if source_organization is not UNSET:
            field_dict["source_organization"] = source_organization
        if data_vintage_start is not UNSET:
            field_dict["data_vintage_start"] = data_vintage_start
        if data_vintage_end is not UNSET:
            field_dict["data_vintage_end"] = data_vintage_end
        if quality_detail is not UNSET:
            field_dict["quality_detail"] = quality_detail
        if source_format is not UNSET:
            field_dict["source_format"] = source_format
        if tile_columns is not UNSET:
            field_dict["tile_columns"] = tile_columns
        if original_srid is not UNSET:
            field_dict["original_srid"] = original_srid
        if current_version is not UNSET:
            field_dict["current_version"] = current_version
        if source_url is not UNSET:
            field_dict["source_url"] = source_url
        if origin is not UNSET:
            field_dict["origin"] = origin
        if origin_uri is not UNSET:
            field_dict["origin_uri"] = origin_uri
        if origin_ref is not UNSET:
            field_dict["origin_ref"] = origin_ref
        if last_refreshed_at is not UNSET:
            field_dict["last_refreshed_at"] = last_refreshed_at
        if last_checked_at is not UNSET:
            field_dict["last_checked_at"] = last_checked_at
        if source_health is not UNSET:
            field_dict["source_health"] = source_health
        if source_health_detail is not UNSET:
            field_dict["source_health_detail"] = source_health_detail
        if schema_drift_status is not UNSET:
            field_dict["schema_drift_status"] = schema_drift_status
        if source_freshness is not UNSET:
            field_dict["source_freshness"] = source_freshness
        if quality_statement is not UNSET:
            field_dict["quality_statement"] = quality_statement
        if last_edited_by_display is not UNSET:
            field_dict["last_edited_by_display"] = last_edited_by_display
        if last_edited_at is not UNSET:
            field_dict["last_edited_at"] = last_edited_at
        if collections is not UNSET:
            field_dict["collections"] = collections
        if record_status is not UNSET:
            field_dict["record_status"] = record_status
        if lineage_summary is not UNSET:
            field_dict["lineage_summary"] = lineage_summary
        if derived_from is not UNSET:
            field_dict["derived_from"] = derived_from
        if update_frequency is not UNSET:
            field_dict["update_frequency"] = update_frequency
        if usage_constraints is not UNSET:
            field_dict["usage_constraints"] = usage_constraints
        if access_constraints is not UNSET:
            field_dict["access_constraints"] = access_constraints
        if sensitivity_classification is not UNSET:
            field_dict["sensitivity_classification"] = sensitivity_classification
        if theme_category is not UNSET:
            field_dict["theme_category"] = theme_category
        if owner_org is not UNSET:
            field_dict["owner_org"] = owner_org
        if published_at is not UNSET:
            field_dict["published_at"] = published_at
        if updated_by is not UNSET:
            field_dict["updated_by"] = updated_by
        if record_type is not UNSET:
            field_dict["record_type"] = record_type
        if raster is not UNSET:
            field_dict["raster"] = raster
        if stac_assets is not UNSET:
            field_dict["stac_assets"] = stac_assets
        if stac_extensions is not UNSET:
            field_dict["stac_extensions"] = stac_extensions
        if language is not UNSET:
            field_dict["language"] = language
        if metadata_warnings is not UNSET:
            field_dict["metadata_warnings"] = metadata_warnings

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.collection_ref import CollectionRef
        from ..models.column_info import ColumnInfo
        from ..models.dataset_response_origin_ref_type_0 import (
            DatasetResponseOriginRefType0,
        )
        from ..models.dataset_response_stac_assets_type_0 import (
            DatasetResponseStacAssetsType0,
        )
        from ..models.derived_from_response import DerivedFromResponse
        from ..models.quality_detail import QualityDetail
        from ..models.raster_metadata import RasterMetadata

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        record_id = UUID(d.pop("record_id"))

        table_name = d.pop("table_name")

        title = d.pop("title")

        def _parse_summary(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        summary = _parse_summary(d.pop("summary"))

        def _parse_feature_count(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        feature_count = _parse_feature_count(d.pop("feature_count"))

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        visibility = d.pop("visibility")

        def _parse_created_by(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_by_type_0 = UUID(data)

                return created_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        created_by = _parse_created_by(d.pop("created_by"))

        created_by_display = d.pop("created_by_display")

        created_at = isoparse(d.pop("created_at"))

        updated_at = isoparse(d.pop("updated_at"))

        def _parse_srid(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        srid = _parse_srid(d.pop("srid", UNSET))

        def _parse_geometry_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type", UNSET))

        has_generic_geometry = d.pop("has_generic_geometry", UNSET)

        def _parse_is_3d(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_3d = _parse_is_3d(d.pop("is_3d", UNSET))

        def _parse_n_dims(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        n_dims = _parse_n_dims(d.pop("n_dims", UNSET))

        def _parse_z_min(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        z_min = _parse_z_min(d.pop("z_min", UNSET))

        def _parse_z_max(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        z_max = _parse_z_max(d.pop("z_max", UNSET))

        def _parse_extent_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                extent_bbox_type_0 = cast(list[float], data)

                return extent_bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        extent_bbox = _parse_extent_bbox(d.pop("extent_bbox", UNSET))

        def _parse_column_info(data: object) -> list[ColumnInfo] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                column_info_type_0 = []
                _column_info_type_0 = data
                for column_info_type_0_item_data in _column_info_type_0:
                    column_info_type_0_item = ColumnInfo.from_dict(
                        column_info_type_0_item_data
                    )

                    column_info_type_0.append(column_info_type_0_item)

                return column_info_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ColumnInfo] | None | Unset, data)

        column_info = _parse_column_info(d.pop("column_info", UNSET))

        def _parse_license_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        license_ = _parse_license_(d.pop("license", UNSET))

        def _parse_attribution(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        attribution = _parse_attribution(d.pop("attribution", UNSET))

        def _parse_source_organization(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_organization = _parse_source_organization(
            d.pop("source_organization", UNSET)
        )

        def _parse_data_vintage_start(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                data_vintage_start_type_0 = isoparse(data).date()

                return data_vintage_start_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        data_vintage_start = _parse_data_vintage_start(
            d.pop("data_vintage_start", UNSET)
        )

        def _parse_data_vintage_end(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                data_vintage_end_type_0 = isoparse(data).date()

                return data_vintage_end_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        data_vintage_end = _parse_data_vintage_end(d.pop("data_vintage_end", UNSET))

        def _parse_quality_detail(data: object) -> None | QualityDetail | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                quality_detail_type_0 = QualityDetail.from_dict(data)

                return quality_detail_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | QualityDetail | Unset, data)

        quality_detail = _parse_quality_detail(d.pop("quality_detail", UNSET))

        def _parse_source_format(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_format = _parse_source_format(d.pop("source_format", UNSET))

        def _parse_tile_columns(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                tile_columns_type_0 = cast(list[str], data)

                return tile_columns_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        tile_columns = _parse_tile_columns(d.pop("tile_columns", UNSET))

        def _parse_original_srid(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        original_srid = _parse_original_srid(d.pop("original_srid", UNSET))

        current_version = d.pop("current_version", UNSET)

        def _parse_source_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_url = _parse_source_url(d.pop("source_url", UNSET))

        def _parse_origin(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        origin = _parse_origin(d.pop("origin", UNSET))

        def _parse_origin_uri(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        origin_uri = _parse_origin_uri(d.pop("origin_uri", UNSET))

        def _parse_origin_ref(
            data: object,
        ) -> DatasetResponseOriginRefType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                origin_ref_type_0 = DatasetResponseOriginRefType0.from_dict(data)

                return origin_ref_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DatasetResponseOriginRefType0 | None | Unset, data)

        origin_ref = _parse_origin_ref(d.pop("origin_ref", UNSET))

        def _parse_last_refreshed_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_refreshed_at_type_0 = isoparse(data)

                return last_refreshed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_refreshed_at = _parse_last_refreshed_at(d.pop("last_refreshed_at", UNSET))

        def _parse_last_checked_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_checked_at_type_0 = isoparse(data)

                return last_checked_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_checked_at = _parse_last_checked_at(d.pop("last_checked_at", UNSET))

        source_health = d.pop("source_health", UNSET)

        def _parse_source_health_detail(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_health_detail = _parse_source_health_detail(
            d.pop("source_health_detail", UNSET)
        )

        schema_drift_status = d.pop("schema_drift_status", UNSET)

        source_freshness = d.pop("source_freshness", UNSET)

        def _parse_quality_statement(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        quality_statement = _parse_quality_statement(d.pop("quality_statement", UNSET))

        def _parse_last_edited_by_display(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        last_edited_by_display = _parse_last_edited_by_display(
            d.pop("last_edited_by_display", UNSET)
        )

        def _parse_last_edited_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_edited_at_type_0 = isoparse(data)

                return last_edited_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_edited_at = _parse_last_edited_at(d.pop("last_edited_at", UNSET))

        def _parse_collections(data: object) -> list[CollectionRef] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                collections_type_0 = []
                _collections_type_0 = data
                for collections_type_0_item_data in _collections_type_0:
                    collections_type_0_item = CollectionRef.from_dict(
                        collections_type_0_item_data
                    )

                    collections_type_0.append(collections_type_0_item)

                return collections_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[CollectionRef] | None | Unset, data)

        collections = _parse_collections(d.pop("collections", UNSET))

        record_status = d.pop("record_status", UNSET)

        def _parse_lineage_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lineage_summary = _parse_lineage_summary(d.pop("lineage_summary", UNSET))

        def _parse_derived_from(data: object) -> DerivedFromResponse | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                derived_from_type_0 = DerivedFromResponse.from_dict(data)

                return derived_from_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DerivedFromResponse | None | Unset, data)

        derived_from = _parse_derived_from(d.pop("derived_from", UNSET))

        def _parse_update_frequency(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        update_frequency = _parse_update_frequency(d.pop("update_frequency", UNSET))

        def _parse_usage_constraints(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        usage_constraints = _parse_usage_constraints(d.pop("usage_constraints", UNSET))

        def _parse_access_constraints(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        access_constraints = _parse_access_constraints(
            d.pop("access_constraints", UNSET)
        )

        def _parse_sensitivity_classification(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sensitivity_classification = _parse_sensitivity_classification(
            d.pop("sensitivity_classification", UNSET)
        )

        def _parse_theme_category(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                theme_category_type_0 = cast(list[str], data)

                return theme_category_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        theme_category = _parse_theme_category(d.pop("theme_category", UNSET))

        def _parse_owner_org(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        owner_org = _parse_owner_org(d.pop("owner_org", UNSET))

        def _parse_published_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                published_at_type_0 = isoparse(data)

                return published_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        published_at = _parse_published_at(d.pop("published_at", UNSET))

        def _parse_updated_by(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                updated_by_type_0 = UUID(data)

                return updated_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        updated_by = _parse_updated_by(d.pop("updated_by", UNSET))

        record_type = d.pop("record_type", UNSET)

        def _parse_raster(data: object) -> None | RasterMetadata | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                raster_type_0 = RasterMetadata.from_dict(data)

                return raster_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RasterMetadata | Unset, data)

        raster = _parse_raster(d.pop("raster", UNSET))

        def _parse_stac_assets(
            data: object,
        ) -> DatasetResponseStacAssetsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                stac_assets_type_0 = DatasetResponseStacAssetsType0.from_dict(data)

                return stac_assets_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DatasetResponseStacAssetsType0 | None | Unset, data)

        stac_assets = _parse_stac_assets(d.pop("stac_assets", UNSET))

        def _parse_stac_extensions(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                stac_extensions_type_0 = cast(list[str], data)

                return stac_extensions_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        stac_extensions = _parse_stac_extensions(d.pop("stac_extensions", UNSET))

        def _parse_language(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        language = _parse_language(d.pop("language", UNSET))

        def _parse_metadata_warnings(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                metadata_warnings_type_0 = cast(list[str], data)

                return metadata_warnings_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        metadata_warnings = _parse_metadata_warnings(d.pop("metadata_warnings", UNSET))

        dataset_response = cls(
            id=id,
            record_id=record_id,
            table_name=table_name,
            title=title,
            summary=summary,
            feature_count=feature_count,
            source_filename=source_filename,
            visibility=visibility,
            created_by=created_by,
            created_by_display=created_by_display,
            created_at=created_at,
            updated_at=updated_at,
            srid=srid,
            geometry_type=geometry_type,
            has_generic_geometry=has_generic_geometry,
            is_3d=is_3d,
            n_dims=n_dims,
            z_min=z_min,
            z_max=z_max,
            extent_bbox=extent_bbox,
            column_info=column_info,
            license_=license_,
            attribution=attribution,
            source_organization=source_organization,
            data_vintage_start=data_vintage_start,
            data_vintage_end=data_vintage_end,
            quality_detail=quality_detail,
            source_format=source_format,
            tile_columns=tile_columns,
            original_srid=original_srid,
            current_version=current_version,
            source_url=source_url,
            origin=origin,
            origin_uri=origin_uri,
            origin_ref=origin_ref,
            last_refreshed_at=last_refreshed_at,
            last_checked_at=last_checked_at,
            source_health=source_health,
            source_health_detail=source_health_detail,
            schema_drift_status=schema_drift_status,
            source_freshness=source_freshness,
            quality_statement=quality_statement,
            last_edited_by_display=last_edited_by_display,
            last_edited_at=last_edited_at,
            collections=collections,
            record_status=record_status,
            lineage_summary=lineage_summary,
            derived_from=derived_from,
            update_frequency=update_frequency,
            usage_constraints=usage_constraints,
            access_constraints=access_constraints,
            sensitivity_classification=sensitivity_classification,
            theme_category=theme_category,
            owner_org=owner_org,
            published_at=published_at,
            updated_by=updated_by,
            record_type=record_type,
            raster=raster,
            stac_assets=stac_assets,
            stac_extensions=stac_extensions,
            language=language,
            metadata_warnings=metadata_warnings,
        )

        dataset_response.additional_properties = d
        return dataset_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
